"""Tenants and accounts administration (S15-1) — platform admin only.

There is no self-registration anywhere in Estimo: a platform admin creates every
workspace and every account. That is the whole authorization story of this router,
and it is why the mount carries `require_platform_admin` rather than each route
arguing about it.

These tables live outside RLS (see accounts_models.py), so every query here runs on
the system session factory and states its own scoping.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from estimo_api.accounts_models import ROLE_PLATFORM_ADMIN, USER_ROLES, Tenant, User
from estimo_api.auth import Principal, current_principal, require_platform_admin
from estimo_api.passwords import hash_password, password_complaint
from estimo_api.projects_models import Project
from estimo_api.routers.auth import UserOut, normalized_email, slugify, system_sessions, user_out

router = APIRouter(prefix="/v1", tags=["accounts"], dependencies=[Depends(require_platform_admin)])


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=60)


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    users: int
    projects: int
    created_at: dt.datetime


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(request: Request) -> list[TenantOut]:
    maker = system_sessions(request)
    async with maker() as session:
        tenants = (
            (await session.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()
        )
        user_counts: dict[uuid.UUID, int] = {
            row[0]: row[1]
            for row in (
                await session.execute(select(User.tenant_id, func.count()).group_by(User.tenant_id))
            ).all()
        }
        # Projects ARE under RLS, and this session is the owner/system one, so the
        # count is honest here where a tenant-scoped session would report zero for
        # every workspace but the caller's own.
        project_counts: dict[uuid.UUID, int] = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(Project.tenant_id, func.count()).group_by(Project.tenant_id)
                )
            ).all()
        }
    return [
        TenantOut(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            users=int(user_counts.get(tenant.id, 0)),
            projects=int(project_counts.get(tenant.id, 0)),
            created_at=tenant.created_at,
        )
        for tenant in tenants
    ]


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(request: Request, payload: TenantIn) -> TenantOut:
    maker = system_sessions(request)
    tenant = Tenant(
        name=payload.name,
        slug=slugify(payload.slug or payload.name, fallback=uuid.uuid4().hex[:8]),
    )
    async with maker() as session:
        session.add(tenant)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"a workspace with slug {tenant.slug!r} already exists",
            ) from exc
        await session.refresh(tenant)
    return TenantOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        users=0,
        projects=0,
        created_at=tenant.created_at,
    )


class UserIn(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=120)
    password: str
    role: str = "user"
    can_sign: bool = False
    tenant_id: uuid.UUID | None = None
    acl_keys: list[str] | None = None

    _email = field_validator("email")(staticmethod(normalized_email))

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        if value not in USER_ROLES:
            raise ValueError(f"role must be one of {', '.join(USER_ROLES)}")
        return value


class UserPatch(BaseModel):
    """Every field optional; omitted means "leave it alone".

    `password` is the one field that is not a plain edit — setting it also bumps the
    account's token version, so a reset ends the sessions the previous password
    opened. That is the point of an administrative reset.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    can_sign: bool | None = None
    is_active: bool | None = None
    tenant_id: uuid.UUID | None = None
    acl_keys: list[str] | None = None
    password: str | None = None

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str | None) -> str | None:
        if value is not None and value not in USER_ROLES:
            raise ValueError(f"role must be one of {', '.join(USER_ROLES)}")
        return value


@router.get("/users", response_model=list[UserOut])
async def list_users(request: Request, tenant_id: uuid.UUID | None = None) -> list[UserOut]:
    maker = system_sessions(request)
    async with maker() as session:
        query = select(User).order_by(User.created_at)
        if tenant_id is not None:
            query = query.where(User.tenant_id == tenant_id)
        users = (await session.execute(query)).scalars().all()
        names: dict[uuid.UUID, str] = {
            row[0]: row[1] for row in (await session.execute(select(Tenant.id, Tenant.name))).all()
        }
    return [user_out(user, tenant_name=names.get(user.tenant_id)) for user in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    payload: UserIn,
    principal: Annotated[Principal, Depends(current_principal)],
) -> UserOut:
    complaint = password_complaint(payload.password)
    if complaint:
        raise HTTPException(status_code=422, detail=complaint)
    # Default to the workspace the admin is currently acting in, which is what
    # "add a user" means from inside a workspace.
    tenant_id = payload.tenant_id or uuid.UUID(principal.tenant)
    maker = system_sessions(request)
    async with maker() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such workspace")
        user = User(
            tenant_id=tenant_id,
            email=payload.email,
            name=payload.name,
            password_hash=hash_password(payload.password),
            role=payload.role,
            can_sign=payload.can_sign,
            acl_keys=payload.acl_keys or None,
            created_by=uuid.UUID(principal.user_id) if principal.user_id else None,
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{payload.email} already has an account",
            ) from exc
        await session.refresh(user)
        tenant_name = tenant.name
    return user_out(user, tenant_name=tenant_name)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    payload: UserPatch,
    principal: Annotated[Principal, Depends(current_principal)],
) -> UserOut:
    maker = system_sessions(request)
    async with maker() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such user")

        demoting = payload.role is not None and payload.role != ROLE_PLATFORM_ADMIN
        disabling = payload.is_active is False
        if user.role == ROLE_PLATFORM_ADMIN and (demoting or disabling):
            remaining = (
                await session.execute(
                    select(func.count())
                    .select_from(User)
                    .where(
                        User.role == ROLE_PLATFORM_ADMIN,
                        User.is_active.is_(True),
                        User.id != user.id,
                    )
                )
            ).scalar_one()
            if not remaining:
                # Locking every administrator out of the deployment is not a
                # recoverable mistake from inside the product.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="this is the last active platform admin",
                )

        if payload.name is not None:
            user.name = payload.name
        if payload.role is not None:
            user.role = payload.role
        if payload.can_sign is not None:
            user.can_sign = payload.can_sign
        if payload.is_active is not None:
            user.is_active = payload.is_active
        if payload.tenant_id is not None:
            user.tenant_id = payload.tenant_id
        if payload.acl_keys is not None:
            user.acl_keys = payload.acl_keys or None
        if payload.password is not None:
            complaint = password_complaint(payload.password)
            if complaint:
                raise HTTPException(
                    status_code=422, detail=complaint
                )
            user.password_hash = hash_password(payload.password)
        # Any of role, tenant, active-state or password changes what a live session
        # is entitled to, so all of them end the sessions already issued rather than
        # letting a demoted account keep its old authority for up to twelve hours.
        if any(
            value is not None
            for value in (
                payload.role,
                payload.is_active,
                payload.tenant_id,
                payload.password,
                payload.can_sign,
            )
        ):
            user.token_version += 1
        await session.commit()
        await session.refresh(user)
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one_or_none()
        tenant_name = tenant.name if tenant else None
    return user_out(user, tenant_name=tenant_name)
