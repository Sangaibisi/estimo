"""Sign-in surface (S15-1): bootstrap, login, whoami, change-my-password.

Unauthenticated by mount — every other router sits behind a role dependency, this
one cannot. Its own routes carry the checks instead.

The first-run gate: a deployment with no accounts is OPEN (the pre-S15 behaviour),
and `POST /v1/auth/bootstrap` closes it forever by creating the first platform
admin. That call needs the setup token, which the operator either sets
(`ESTIMO_SETUP_TOKEN`) or reads from the startup log. Without it, "the first person
to find the URL becomes the administrator" — which is exactly what an internet-
reachable fresh install must not offer.
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from estimo_api.accounts_models import ROLE_PLATFORM_ADMIN, Tenant, User
from estimo_api.auth import Principal, current_principal
from estimo_api.passwords import (
    hash_password,
    issue_session,
    password_complaint,
    verify_password,
)

logger = logging.getLogger("estimo.api.auth")

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str, *, fallback: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().casefold()).strip("-")
    return (slug or fallback)[:60]


def system_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    """The session factory for tables that live outside RLS (tenants, users)."""
    maker: async_sessionmaker[AsyncSession] = request.app.state.system_sessionmaker
    return maker


# Deliberately not pydantic's EmailStr: that pulls in `email-validator`, which is
# only present here transitively. An address we never send mail to needs to be
# plausible, not RFC-certified — and a transitive dependency silently disappearing
# is a whole class of outage (AGENTS: no undeclared dependencies).
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def normalized_email(value: str) -> str:
    address = value.strip().lower()
    if not EMAIL_RE.match(address) or len(address) > 200:
        raise ValueError("not a valid email address")
    return address


class BootstrapIn(BaseModel):
    setup_token: str
    email: str
    name: str = Field(min_length=1, max_length=120)
    password: str
    workspace: str = Field(default="Default workspace", max_length=120)

    _email = field_validator("email")(staticmethod(normalized_email))


class LoginIn(BaseModel):
    email: str
    password: str

    _email = field_validator("email")(staticmethod(normalized_email))


class SessionOut(BaseModel):
    token: str
    expires_at: dt.datetime
    user: UserOut


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    can_sign: bool
    is_active: bool
    tenant_id: uuid.UUID
    tenant_name: str | None = None
    acl_keys: list[str] | None = None
    last_login_at: dt.datetime | None = None


def user_out(user: User, *, tenant_name: str | None = None) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        can_sign=user.can_sign,
        is_active=user.is_active,
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
        acl_keys=user.acl_keys,
        last_login_at=user.last_login_at,
    )


@router.post("/bootstrap", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def bootstrap(request: Request, payload: BootstrapIn) -> SessionOut:
    """Create the first platform admin. Refused once any account exists."""
    expected: str = request.app.state.setup_token
    # Compared in constant time and only after the "already bootstrapped" check
    # below would have passed anyway — a wrong token and an already-initialised
    # deployment must not be distinguishable by timing.
    if not expected or not hmac.compare_digest(payload.setup_token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid setup token")
    complaint = password_complaint(payload.password)
    if complaint:
        raise HTTPException(status_code=422, detail=complaint)

    maker = system_sessions(request)
    async with maker() as session:
        existing = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this deployment already has accounts — sign in instead",
            )
        from estimo_api.tenancy import DEFAULT_TENANT

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(DEFAULT_TENANT)))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                id=uuid.UUID(DEFAULT_TENANT),
                name=payload.workspace,
                slug=slugify(payload.workspace, fallback="default"),
            )
            session.add(tenant)
        else:
            # The migration seeds a placeholder name; the operator's own wording for
            # their workspace is better than ours.
            tenant.name = payload.workspace
        user = User(
            tenant_id=tenant.id,
            email=payload.email,
            name=payload.name,
            password_hash=hash_password(payload.password),
            role=ROLE_PLATFORM_ADMIN,
            can_sign=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        tenant_name = tenant.name

    request.app.state.accounts_exist = True
    logger.warning(
        "deployment bootstrapped: %s is the first platform admin; the API is no "
        "longer open to anonymous callers",
        user.email,
    )
    token, expires = issue_session(
        request.app.state.session_key,
        user_id=str(user.id),
        tenant=str(user.tenant_id),
        role=user.role,
        can_sign=user.can_sign,
        token_version=user.token_version,
    )
    return SessionOut(token=token, expires_at=expires, user=user_out(user, tenant_name=tenant_name))


@router.post("/login", response_model=SessionOut)
async def login(request: Request, payload: LoginIn) -> SessionOut:
    maker = system_sessions(request)
    async with maker() as session:
        user = (
            await session.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()
        # The password is verified even when the account is missing or disabled, so
        # a valid address cannot be told from an invalid one by response time.
        stored = user.password_hash if user is not None else _DUMMY_HASH
        ok = verify_password(payload.password, stored)
        if user is None or not ok or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
            )
        user.last_login_at = dt.datetime.now(dt.UTC)
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one_or_none()
        tenant_name = tenant.name if tenant else None
        await session.commit()
        await session.refresh(user)

    token, expires = issue_session(
        request.app.state.session_key,
        user_id=str(user.id),
        tenant=str(user.tenant_id),
        role=user.role,
        can_sign=user.can_sign,
        token_version=user.token_version,
    )
    return SessionOut(token=token, expires_at=expires, user=user_out(user, tenant_name=tenant_name))


# A syntactically valid hash of a value nobody holds. Keeps the failed-login path on
# the same scrypt cost as the successful one.
_DUMMY_HASH = hash_password(uuid.uuid4().hex)


class MeOut(BaseModel):
    authenticated: bool
    # False only on a deployment that has not been bootstrapped yet — the web client
    # uses it to route to the setup screen instead of the login screen.
    accounts_exist: bool
    user: UserOut | None = None
    tenant: uuid.UUID | None = None
    role: str | None = None
    can_sign: bool = False


@router.get("/me", response_model=MeOut)
async def me(request: Request) -> MeOut:
    """Who the caller is — deliberately never 401s.

    The web client asks this before it knows whether anyone is signed in, and a 401
    here would be indistinguishable from a broken deployment. An anonymous caller
    gets `authenticated: false` and enough state to pick the right screen.
    """
    from fastapi.security.utils import get_authorization_scheme_param

    maker = system_sessions(request)
    async with maker() as session:
        accounts = bool(
            (await session.execute(select(func.count()).select_from(User))).scalar_one()
        )

    scheme, token = get_authorization_scheme_param(request.headers.get("Authorization", ""))
    if not accounts or scheme.lower() != "bearer" or not token:
        return MeOut(authenticated=False, accounts_exist=accounts)

    from estimo_api.auth import _local_principal

    principal = await _local_principal(request, token)
    if principal is None or principal.user_id is None:
        return MeOut(authenticated=False, accounts_exist=accounts)
    async with maker() as session:
        user = (
            await session.execute(select(User).where(User.id == uuid.UUID(principal.user_id)))
        ).scalar_one()
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(principal.tenant)))
        ).scalar_one_or_none()
    return MeOut(
        authenticated=True,
        accounts_exist=True,
        user=user_out(user, tenant_name=tenant.name if tenant else None),
        tenant=uuid.UUID(principal.tenant),
        role=principal.role,
        can_sign=principal.can_sign,
    )


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: Request,
    payload: PasswordChangeIn,
    principal: Annotated[Principal, Depends(current_principal)],
) -> None:
    """Change your own password. Every session already issued stops working."""
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="this caller has no local account",
        )
    complaint = password_complaint(payload.new_password)
    if complaint:
        raise HTTPException(status_code=422, detail=complaint)
    maker = system_sessions(request)
    async with maker() as session:
        user = (
            await session.execute(select(User).where(User.id == uuid.UUID(principal.user_id)))
        ).scalar_one()
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="current password is wrong"
            )
        user.password_hash = hash_password(payload.new_password)
        user.token_version += 1
        await session.commit()
