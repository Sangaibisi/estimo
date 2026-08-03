"""Estimo MCP server (S10-5): read-only tools over the existing service layer.

Mounted into the FastAPI app at /mcp over streamable HTTP (FastMCP 3.x). When OIDC is
configured the MCP endpoint is an OAuth2 resource server (FastMCP `JWTVerifier`) that
validates the same bearer tokens as the REST API; each tool pins the caller's tenant
from the token BEFORE querying, so RLS isolation applies identically. With auth
disabled the tools run open on the DEFAULT_TENANT (single-tenant mode), matching the
REST API.

Tools are strictly READ: query estimates, pull an estimate's evidence-linked BoE
lines, and fetch a work-item decomposition. No tool mutates state.
"""

from __future__ import annotations

import uuid
from typing import Any

from estimo_pipeline import PipelineState
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from estimo_api.auth import AuthSettings, _pluck, discover_jwks_uri, tenant_to_uuid
from estimo_api.estimates_models import EstimateRecord
from estimo_api.tenancy import DEFAULT_TENANT, bind_tenant_guc, set_current_tenant
from estimo_core import BoeDocument


def build_mcp(sessionmaker: async_sessionmaker[Any], auth: AuthSettings) -> FastMCP:
    verifier = None
    if auth.enabled:
        issuer, jwks_uri = discover_jwks_uri(auth.issuer)
        verifier = JWTVerifier(
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=auth.audience,
            algorithm=auth.algorithms[0] if auth.algorithms else "RS256",
        )
    mcp: FastMCP = FastMCP(name="estimo", auth=verifier)

    def _pin_tenant() -> None:
        # Scope the query to the caller's tenant from the validated token; without
        # auth every call runs single-tenant on the default tenant.
        if not auth.enabled:
            set_current_tenant(DEFAULT_TENANT)
            return
        token = get_access_token()
        claims = getattr(token, "claims", None) or {}
        tenant = _pluck(claims, auth.tenant_claim)
        set_current_tenant(
            tenant_to_uuid(tenant) if isinstance(tenant, str) and tenant else DEFAULT_TENANT
        )

    async def _session() -> Any:
        _pin_tenant()
        session = sessionmaker()
        bind_tenant_guc(session)
        return session

    @mcp.tool
    async def list_estimates(limit: int = 20) -> list[dict[str, Any]]:
        """List estimates (BRD reference, title, status, work-item count)."""
        session = await _session()
        async with session:
            rows = await session.execute(
                select(EstimateRecord).order_by(EstimateRecord.created_at.desc()).limit(limit)
            )
            out = []
            for record in rows.scalars():
                state = PipelineState.model_validate(record.state)
                out.append(
                    {
                        "id": str(record.id),
                        "brd_ref": record.brd_ref,
                        "title": record.title,
                        "status": record.status,
                        "work_items": len(state.work_items),
                        "has_boe": record.boe is not None,
                    }
                )
            return out

    @mcp.tool
    async def get_estimate_lines(estimate_id: str) -> list[dict[str, Any]]:
        """Evidence-linked BoE lines for a signed estimate (band + evidence URIs)."""
        session = await _session()
        async with session:
            record = await session.get(EstimateRecord, uuid.UUID(estimate_id))
            if record is None or record.boe is None:
                return []
            boe = BoeDocument.model_validate(record.boe)
            return [
                {
                    "work_item_id": line.work_item_id,
                    "optimistic": line.range.optimistic,
                    "likely": line.range.likely,
                    "pessimistic": line.range.pessimistic,
                    "confidence": line.confidence,
                    "evidence": [ref.uri for ref in line.evidence],
                }
                for line in boe.lines
            ]

    @mcp.tool
    async def get_decomposition(estimate_id: str) -> list[dict[str, Any]]:
        """Work-item decomposition of an estimate (id, title, module tags)."""
        session = await _session()
        async with session:
            record = await session.get(EstimateRecord, uuid.UUID(estimate_id))
            if record is None:
                return []
            state = PipelineState.model_validate(record.state)
            return [
                {
                    "id": item.id,
                    "title": item.title,
                    "module_tags": list(item.module_tags),
                    "requirement_ids": list(item.requirement_ids),
                }
                for item in state.work_items
            ]

    return mcp
