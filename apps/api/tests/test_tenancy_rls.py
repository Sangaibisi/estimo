"""S10-2: row-level security genuinely isolates tenants under the runtime app role.

The `estimo` test role is a superuser and BYPASSES RLS, so a real isolation test must
connect as the NOSUPERUSER/NOBYPASSRLS `estimo_app` role that the API uses in
production. This test creates that connection explicitly and proves cross-tenant reads
return nothing and cross-tenant writes are refused.
"""

import uuid

import pytest
from sqlalchemy import make_url, text
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

    # Rewrite the URL's credentials structurally. A string replace would silently
    # no-op when the environment's password differs (CI vs local), leaving the test
    # connected as the OWNER — which BYPASSES RLS and would make this suite assert
    # nothing while looking green.
    app_url = make_url(database_url).set(username="estimo_app", password=APP_PASSWORD)
    engine = create_async_engine(app_url)

    # Prove we are actually testing the RLS path before any assertion runs.
    async with engine.connect() as conn:
        role, is_super, bypass = (
            await conn.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
    assert role == "estimo_app", f"connected as {role!r}, not the RLS-bound app role"
    assert not is_super and not bypass, "app role would bypass RLS; the test is meaningless"

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


async def test_cross_tenant_same_name_does_not_collide(  # type: ignore[no-untyped-def]
    app_sessionmaker, clean_tables
) -> None:
    """A global unique key would let tenant B's insert collide with tenant A's row
    (DoS + existence oracle). Composite (tenant_id, name) keys must allow the same
    connection name in two tenants."""
    import uuid as _uuid

    from estimo_api.tenancy import set_current_tenant

    maker = app_sessionmaker

    async def _add_connection(tenant: str) -> None:
        set_current_tenant(tenant)
        async with maker() as session:
            bind_tenant_guc(session)
            await session.execute(
                text(
                    "INSERT INTO connections (id, kind, name, base_url, config) "
                    "VALUES (:id, 'git', 'shared-name', 'https://x', '{}'::jsonb)"
                ),
                {"id": _uuid.uuid4()},
            )
            await session.commit()

    await _add_connection(TENANT_A)
    await _add_connection(TENANT_B)  # same name, different tenant → no IntegrityError

    set_current_tenant(TENANT_A)
    async with maker() as session:
        bind_tenant_guc(session)
        count = await session.scalar(text("SELECT count(*) FROM connections"))
        assert count == 1  # each tenant still sees only its own
