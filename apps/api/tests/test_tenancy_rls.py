"""S10-2: row-level security genuinely isolates tenants under the runtime app role.

The `estimo` test role is a superuser and BYPASSES RLS, so a real isolation test must
connect as the NOSUPERUSER/NOBYPASSRLS `estimo_app` role that the API uses in
production. This test creates that connection explicitly and proves cross-tenant reads
return nothing and cross-tenant writes are refused.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from estimo_api.tenancy import bind_tenant_guc

pytestmark = pytest.mark.db

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
APP_PASSWORD = "rls-test-pw"


@pytest.fixture
async def app_sessionmaker(database_url: str):  # type: ignore[no-untyped-def]
    """A sessionmaker connecting as `estimo_app` (RLS applies). The migration created
    the role NOLOGIN; give it a password + login for the test."""
    owner = create_async_engine(database_url)
    async with owner.begin() as conn:
        await conn.execute(text(f"ALTER ROLE estimo_app LOGIN PASSWORD '{APP_PASSWORD}'"))
    await owner.dispose()

    # Swap the credentials in the URL for the app role. asyncpg needs a TCP host
    # (the app role authenticates via scram, unlike the trust-socket owner).
    app_url = database_url.replace("estimo:change-me", f"estimo_app:{APP_PASSWORD}")
    engine = create_async_engine(app_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _insert_estimate(session: AsyncSession, tenant: str, brd_ref: str) -> uuid.UUID:
    from estimo_api.tenancy import set_current_tenant

    set_current_tenant(tenant)
    estimate_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO estimates (id, brd_ref, title, status, state) "
            "VALUES (:id, :ref, :ref, 'boe_draft', '{}'::jsonb)"
        ),
        {"id": estimate_id, "ref": brd_ref},
    )
    await session.commit()
    return estimate_id


async def test_rls_isolates_reads_and_writes(app_sessionmaker, clean_tables) -> None:  # type: ignore[no-untyped-def]
    from estimo_api.tenancy import set_current_tenant

    maker = app_sessionmaker

    # Tenant A writes one estimate.
    async with maker() as session:
        bind_tenant_guc(session)
        await _insert_estimate(session, TENANT_A, "AUR-A-1")

    # Tenant B writes one estimate.
    async with maker() as session:
        bind_tenant_guc(session)
        await _insert_estimate(session, TENANT_B, "AUR-B-1")

    # Tenant A sees ONLY its own row.
    async with maker() as session:
        bind_tenant_guc(session)
        set_current_tenant(TENANT_A)
        refs = list((await session.execute(text("SELECT brd_ref FROM estimates"))).scalars())
        assert refs == ["AUR-A-1"]

    # Tenant B sees ONLY its own row.
    async with maker() as session:
        bind_tenant_guc(session)
        set_current_tenant(TENANT_B)
        refs = list((await session.execute(text("SELECT brd_ref FROM estimates"))).scalars())
        assert refs == ["AUR-B-1"]

    # A cross-tenant write is refused by the WITH CHECK clause: tenant A cannot
    # insert a row stamped for tenant B.
    async with maker() as session:
        bind_tenant_guc(session)
        set_current_tenant(TENANT_A)
        with pytest.raises(ProgrammingError):
            await session.execute(
                text(
                    "INSERT INTO estimates (id, brd_ref, title, status, state, tenant_id) "
                    "VALUES (:id, 'X', 'X', 'boe_draft', '{}'::jsonb, :other)"
                ),
                {"id": uuid.uuid4(), "other": TENANT_B},
            )
            await session.commit()


async def test_app_role_cannot_bypass_rls(app_sessionmaker, clean_tables) -> None:  # type: ignore[no-untyped-def]
    """With no tenant GUC set, the app role sees nothing (deny by default)."""
    maker = app_sessionmaker
    async with maker() as session:
        bind_tenant_guc(session)
        await _insert_estimate(session, TENANT_A, "AUR-A-2")

    # A fresh connection with the GUC left at the default tenant sees no tenant-A rows.
    async with maker() as session:
        bind_tenant_guc(session)
        from estimo_api.tenancy import DEFAULT_TENANT, set_current_tenant

        set_current_tenant(DEFAULT_TENANT)
        refs = list((await session.execute(text("SELECT brd_ref FROM estimates"))).scalars())
        assert "AUR-A-2" not in refs
