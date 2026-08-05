"""Projects and the repository map (S14-1) — the product's cornerstone surface.

Reading is open to every account in the tenant: the map is how people understand
what the landscape looks like, and hiding it would make the estimates built on it
unreadable. WRITING — creating projects, adding nodes, drawing relations — is the
project owner's job, so those routes carry `require_project_owner`.

All five tables are under RLS, so every query here runs on the tenant-scoped session
and inherits isolation from the GUC. A platform admin working inside someone else's
workspace sends `X-Estimo-Tenant`; nothing in this file has to know that happened.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from estimo_connectors.db import Connection, SyncRun
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from estimo_api.auth import Principal, current_principal, require_project_owner
from estimo_api.db import get_session
from estimo_api.projects_models import (
    NODE_TYPES,
    RELATION_KINDS,
    Project,
    ProjectRelation,
    ProjectRepo,
)

router = APIRouter(prefix="/v1/projects", tags=["projects"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
OwnerDep = Annotated[Principal, Depends(require_project_owner)]


async def acting_tenant(principal: Annotated[Principal, Depends(current_principal)]) -> uuid.UUID:
    """The workspace this request belongs to, as a filter value.

    Every query below states this filter EXPLICITLY even though RLS already enforces
    it. That is the defense-in-depth tenancy.py describes and the rest of the code
    only assumes: RLS is the database's backstop for when the application forgets,
    not the application's excuse to never scope. It also fails safe on the one
    deployment where the backstop is absent — a developer connected as the owner
    role, where RLS is bypassed and an unscoped SELECT would quietly return every
    workspace's map.
    """
    return uuid.UUID(principal.tenant)


TenantDep = Annotated[uuid.UUID, Depends(acting_tenant)]

_KEY_ALPHABET = "".join(chr(code) for code in range(ord("A"), ord("Z") + 1)) + "0123456789-_"


def project_key(name: str) -> str:
    """An initials key from a project name: "Core Integration Platform" → "CIP"."""
    words = [word for word in "".join(c if c.isalnum() else " " for c in name).split() if word]
    initials = "".join(word[0] for word in words).upper()[:4]
    return initials or "PRJ"


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    key: str | None = Field(default=None, max_length=12)

    @field_validator("key")
    @classmethod
    def _clean_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = value.strip().upper()
        if not key or any(char not in _KEY_ALPHABET for char in key):
            raise ValueError("key must be letters, digits, - or _")
        return key


class ProjectOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    owner_id: uuid.UUID | None
    repos: int = 0
    relations: int = 0
    created_at: dt.datetime


class RepoIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider: str = Field(default="git", max_length=20)
    node_type: str = "be"
    connection_id: uuid.UUID | None = None
    pos_x: float | None = None
    pos_y: float | None = None

    @field_validator("node_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in NODE_TYPES:
            raise ValueError(f"node_type must be one of {', '.join(NODE_TYPES)}")
        return value


class RepoPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=20)
    node_type: str | None = None
    # Explicitly nullable on purpose: sending null DETACHES the node from its
    # connection (it stays on the map as a declared repository).
    connection_id: uuid.UUID | None = None
    detach_connection: bool = False
    pos_x: float | None = None
    pos_y: float | None = None
    # True resets placement to the automatic layer layout.
    reset_position: bool = False

    @field_validator("node_type")
    @classmethod
    def _known_type(cls, value: str | None) -> str | None:
        if value is not None and value not in NODE_TYPES:
            raise ValueError(f"node_type must be one of {', '.join(NODE_TYPES)}")
        return value


class RelationIn(BaseModel):
    from_repo_id: uuid.UUID
    to_repo_id: uuid.UUID
    kind: str = "api"

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in RELATION_KINDS:
            raise ValueError(f"kind must be one of {', '.join(RELATION_KINDS)}")
        return value


async def _load_project(session: AsyncSession, project_id: uuid.UUID, tenant: uuid.UUID) -> Project:
    project = (
        await session.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant)
        )
    ).scalar_one_or_none()
    if project is None:
        # RLS already makes another tenant's project invisible, so "not found" here
        # is the honest answer for both a wrong id and a foreign one.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such project")
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: SessionDep, tenant: TenantDep) -> list[ProjectOut]:
    projects = (
        (
            await session.execute(
                select(Project).where(Project.tenant_id == tenant).order_by(Project.created_at)
            )
        )
        .scalars()
        .all()
    )
    repos = (
        (
            await session.execute(
                select(ProjectRepo.project_id).where(ProjectRepo.tenant_id == tenant)
            )
        )
        .scalars()
        .all()
    )
    relations = (
        (
            await session.execute(
                select(ProjectRelation.project_id).where(ProjectRelation.tenant_id == tenant)
            )
        )
        .scalars()
        .all()
    )
    return [
        ProjectOut(
            id=project.id,
            key=project.key,
            name=project.name,
            owner_id=project.owner_id,
            repos=sum(1 for pid in repos if pid == project.id),
            relations=sum(1 for pid in relations if pid == project.id),
            created_at=project.created_at,
        )
        for project in projects
    ]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    session: SessionDep, payload: ProjectIn, principal: OwnerDep
) -> ProjectOut:
    project = Project(
        key=payload.key or project_key(payload.name),
        name=payload.name,
        owner_id=uuid.UUID(principal.user_id) if principal.user_id else None,
    )
    session.add(project)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a project with key {project.key!r} already exists in this workspace",
        ) from exc
    await session.refresh(project)
    return ProjectOut(
        id=project.id,
        key=project.key,
        name=project.name,
        owner_id=project.owner_id,
        created_at=project.created_at,
    )


@router.patch("/{project_id}", response_model=ProjectOut)
async def rename_project(
    session: SessionDep,
    tenant: TenantDep,
    project_id: uuid.UUID,
    payload: ProjectIn,
    principal: OwnerDep,
) -> ProjectOut:
    project = await _load_project(session, project_id, tenant)
    project.name = payload.name
    if payload.key:
        project.key = payload.key
    await session.commit()
    await session.refresh(project)
    return ProjectOut(
        id=project.id,
        key=project.key,
        name=project.name,
        owner_id=project.owner_id,
        created_at=project.created_at,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    session: SessionDep, tenant: TenantDep, project_id: uuid.UUID, principal: OwnerDep
) -> None:
    project = await _load_project(session, project_id, tenant)
    await session.delete(project)
    await session.commit()


@router.get("/{project_id}/map")
async def read_map(session: SessionDep, tenant: TenantDep, project_id: uuid.UUID) -> dict[str, Any]:
    """The project's map: nodes (with their connection's live facts) and relations."""
    project = await _load_project(session, project_id, tenant)
    repos = (
        (
            await session.execute(
                select(ProjectRepo)
                .where(ProjectRepo.project_id == project_id, ProjectRepo.tenant_id == tenant)
                .order_by(ProjectRepo.created_at)
            )
        )
        .scalars()
        .all()
    )
    relations = (
        (
            await session.execute(
                select(ProjectRelation)
                .where(
                    ProjectRelation.project_id == project_id, ProjectRelation.tenant_id == tenant
                )
                .order_by(ProjectRelation.created_at)
            )
        )
        .scalars()
        .all()
    )

    linked = {repo.connection_id for repo in repos if repo.connection_id}
    connections: dict[uuid.UUID, dict[str, Any]] = {}
    if linked:
        rows = (
            (
                await session.execute(
                    select(Connection).where(
                        Connection.id.in_(linked), Connection.tenant_id == tenant
                    )
                )
            )
            .scalars()
            .all()
        )
        for connection in rows:
            latest = await session.scalar(
                select(SyncRun)
                .where(SyncRun.connection_id == connection.id)
                .order_by(SyncRun.started_at.desc())
                .limit(1)
            )
            connections[connection.id] = {
                "id": str(connection.id),
                "kind": connection.kind,
                "name": connection.name,
                "base_url": connection.base_url,
                "status": latest.status if latest else None,
                "synced_at": latest.started_at.isoformat() if latest else None,
                # The code-graph shape is what makes a synced node worth more than a
                # drawn one; it is the only part of the run stats the map shows.
                "graph": (latest.stats or {}).get("graph") if latest else None,
            }

    return {
        "project": {"id": str(project.id), "key": project.key, "name": project.name},
        "repos": [
            {
                "id": str(repo.id),
                "name": repo.name,
                "provider": repo.provider,
                "node_type": repo.node_type,
                "connection_id": str(repo.connection_id) if repo.connection_id else None,
                "connection": connections.get(repo.connection_id) if repo.connection_id else None,
                "pos_x": repo.pos_x,
                "pos_y": repo.pos_y,
            }
            for repo in repos
        ],
        "relations": [
            {
                "id": str(relation.id),
                "from_repo_id": str(relation.from_repo_id),
                "to_repo_id": str(relation.to_repo_id),
                "kind": relation.kind,
            }
            for relation in relations
        ],
    }


@router.post("/{project_id}/repos", status_code=status.HTTP_201_CREATED)
async def add_repo(
    session: SessionDep,
    tenant: TenantDep,
    project_id: uuid.UUID,
    payload: RepoIn,
    principal: OwnerDep,
) -> dict[str, Any]:
    await _load_project(session, project_id, tenant)
    if payload.connection_id is not None:
        # RLS scopes this lookup, so a connection from another tenant reads as
        # missing rather than as a link across the boundary.
        exists = await session.scalar(
            select(Connection.id).where(
                Connection.id == payload.connection_id, Connection.tenant_id == tenant
            )
        )
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such connection")
    repo = ProjectRepo(
        project_id=project_id,
        name=payload.name,
        provider=payload.provider,
        node_type=payload.node_type,
        connection_id=payload.connection_id,
        pos_x=payload.pos_x,
        pos_y=payload.pos_y,
    )
    session.add(repo)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{payload.name!r} is already on this map",
        ) from exc
    await session.refresh(repo)
    return {"id": str(repo.id), "name": repo.name, "node_type": repo.node_type}


@router.patch("/{project_id}/repos/{repo_id}")
async def update_repo(
    session: SessionDep,
    tenant: TenantDep,
    project_id: uuid.UUID,
    repo_id: uuid.UUID,
    payload: RepoPatch,
    principal: OwnerDep,
) -> dict[str, Any]:
    repo = (
        await session.execute(
            select(ProjectRepo).where(
                ProjectRepo.id == repo_id,
                ProjectRepo.project_id == project_id,
                ProjectRepo.tenant_id == tenant,
            )
        )
    ).scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such node")
    if payload.name is not None:
        repo.name = payload.name
    if payload.provider is not None:
        repo.provider = payload.provider
    if payload.node_type is not None:
        repo.node_type = payload.node_type
    if payload.detach_connection:
        repo.connection_id = None
    elif payload.connection_id is not None:
        exists = await session.scalar(
            select(Connection.id).where(
                Connection.id == payload.connection_id, Connection.tenant_id == tenant
            )
        )
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such connection")
        repo.connection_id = payload.connection_id
    if payload.reset_position:
        repo.pos_x = None
        repo.pos_y = None
    elif payload.pos_x is not None and payload.pos_y is not None:
        repo.pos_x = payload.pos_x
        repo.pos_y = payload.pos_y
    await session.commit()
    return {"id": str(repo.id), "name": repo.name, "node_type": repo.node_type}


@router.delete("/{project_id}/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repo(
    session: SessionDep,
    tenant: TenantDep,
    project_id: uuid.UUID,
    repo_id: uuid.UUID,
    principal: OwnerDep,
) -> None:
    result = await session.execute(
        delete(ProjectRepo).where(
            ProjectRepo.id == repo_id,
            ProjectRepo.project_id == project_id,
            ProjectRepo.tenant_id == tenant,
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such node")
    await session.commit()


@router.post("/{project_id}/relations", status_code=status.HTTP_201_CREATED)
async def add_relation(
    session: SessionDep,
    tenant: TenantDep,
    project_id: uuid.UUID,
    payload: RelationIn,
    principal: OwnerDep,
) -> dict[str, Any]:
    if payload.from_repo_id == payload.to_repo_id:
        raise HTTPException(
            status_code=422,
            detail="a repository cannot consume itself",
        )
    endpoints = (
        (
            await session.execute(
                select(ProjectRepo.id).where(
                    ProjectRepo.project_id == project_id,
                    ProjectRepo.tenant_id == tenant,
                    ProjectRepo.id.in_([payload.from_repo_id, payload.to_repo_id]),
                )
            )
        )
        .scalars()
        .all()
    )
    # Both ends must be on THIS project's map: an edge across projects would draw a
    # relation nobody can see from either side.
    if len(set(endpoints)) != 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="both ends of a relation must be nodes of this project",
        )
    relation = ProjectRelation(
        project_id=project_id,
        from_repo_id=payload.from_repo_id,
        to_repo_id=payload.to_repo_id,
        kind=payload.kind,
    )
    session.add(relation)
    try:
        await session.commit()
    except IntegrityError:
        # Drawing the same edge twice is the user saying the same true thing again.
        await session.rollback()
        existing = await session.scalar(
            select(ProjectRelation.id).where(
                ProjectRelation.tenant_id == tenant,
                ProjectRelation.from_repo_id == payload.from_repo_id,
                ProjectRelation.to_repo_id == payload.to_repo_id,
                ProjectRelation.kind == payload.kind,
            )
        )
        return {"id": str(existing), "kind": payload.kind, "created": False}
    await session.refresh(relation)
    return {"id": str(relation.id), "kind": relation.kind, "created": True}


@router.delete("/{project_id}/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relation(
    session: SessionDep,
    tenant: TenantDep,
    project_id: uuid.UUID,
    relation_id: uuid.UUID,
    principal: OwnerDep,
) -> None:
    result = await session.execute(
        delete(ProjectRelation).where(
            ProjectRelation.id == relation_id,
            ProjectRelation.project_id == project_id,
            ProjectRelation.tenant_id == tenant,
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such relation")
    await session.commit()
