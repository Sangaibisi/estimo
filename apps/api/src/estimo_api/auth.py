"""OIDC bearer-token auth + role model (S10-1) — provider-agnostic, self-hosted.

The customer points Estimo at THEIR OWN IdP (Keycloak / Entra / Okta / …). Every
provider collapses to four env values: issuer, audience, a dotted role-claim path,
and a dotted tenant-claim path. No provider SDK is involved — PyJWT validates the
bearer JWT against the IdP's JWKS (fetched from the discovery document).

Web-verified hardening (2026):
- python-jose is banned (abandoned); PyJWT + PyJWKClient is the maintained choice
  (PyJWKClient caches the JWKS and refreshes on key rotation; the pinned PyJWT no
  longer wipes its cache on a failed refresh — bug #1162 is fixed upstream).
- Algorithms are pinned to an asymmetric allow-list (never HS*/none — alg-confusion).
- iss/aud/exp/sub are required and validated; small leeway for clock skew.
- The role claim is normalized (list OR space-delimited string) so a bare-string
  claim is never iterated per-character.

Auth is OPT-IN: with no issuer configured the API runs open in single-tenant mode
(the historical behavior). This module never logs token contents.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel, Field

from estimo_core import PUBLIC_ACL

logger = logging.getLogger("estimo.api.auth")

# The tenant column is a UUID (RLS keys on it). IdPs supply a tenant identifier of
# their own shape (realm name, org id, uuid), so any string is folded to a stable
# UUID — the same claim always maps to the same tenant.
_TENANT_NAMESPACE = uuid.UUID("6f1d8b2e-0000-4000-8000-657374696d6f")


def tenant_to_uuid(raw: str) -> str:
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return str(uuid.uuid5(_TENANT_NAMESPACE, raw))


def _as_role_list(claim: Any) -> list[str]:
    """Normalize a role claim to a list of strings. IdPs emit roles as a JSON list
    (Keycloak) OR a space-delimited string (OIDC `scope`); a bare string must not be
    iterated per-character (which would silently deny every role)."""
    if claim is None:
        return []
    if isinstance(claim, str):
        return claim.split()
    if isinstance(claim, list | tuple | set | frozenset):
        return [str(role) for role in claim]
    return []


def discover_jwks_uri(issuer: str) -> tuple[str, str]:
    """Return (canonical_issuer, jwks_uri) from the OIDC discovery document."""
    response = httpx.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10.0)
    response.raise_for_status()
    document = response.json()
    return document["issuer"], document["jwks_uri"]


class AuthSettings(BaseModel):
    """OIDC configuration (ESTIMO_AUTH__*). Empty issuer => auth disabled."""

    issuer: str = ""
    audience: str = ""
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    role_claim: str = "realm_access.roles"
    tenant_claim: str = "tenant"
    # Dotted path to the claim carrying the caller's source-system audiences — the
    # groups/space-keys that Confluence restrictions are expressed in. Empty (the
    # default) means Estimo cannot attribute ANY audience to a caller, and the ACL
    # clamp falls back to PUBLIC_ACL. It never falls back to "everything": a
    # pre-filter that cannot identify the reader must show less, not more
    # (SECURITY.md).
    acl_claim: str = ""
    jwks_ttl_seconds: int = 300
    leeway_seconds: int = 30

    @property
    def enabled(self) -> bool:
        return bool(self.issuer)


class Principal(BaseModel):
    """The authenticated caller distilled to what the app authorizes on."""

    subject: str
    tenant: str
    roles: frozenset[str]
    # Source-system audiences this caller can be PROVEN to hold. Never taken from a
    # request body — see clamp_acl_keys.
    acl_keys: frozenset[str] = frozenset({PUBLIC_ACL})


def clamp_acl_keys(principal: Principal, requested: list[str] | None) -> list[str]:
    """The ACL keys a request may actually search with.

    SECURITY.md: source ACLs are enforced as a PRE-FILTER at query time, and the
    pre-filter must never widen access. A caller-supplied key list is a *narrowing*
    preference, never an authorization — before this existed, POST /v1/canonical
    passed the request body's acl_keys straight into retrieval, so any reviewer could
    name a restricted audience, pull its text into a draft body, and read it back.

    So: the caller's proven audiences are the ceiling, and `requested` may only
    intersect it. An empty intersection is an error rather than a silent widening to
    public, because silently returning public results for a restricted query looks
    like "that space has nothing about X" — a false negative the curator would act on.
    """
    entitled = principal.acl_keys or frozenset({PUBLIC_ACL})
    if requested is None:
        return sorted(entitled)
    narrowed = entitled & frozenset(requested)
    if not narrowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "none of the requested acl_keys are held by this caller; "
                f"available: {sorted(entitled)}"
            ),
        )
    return sorted(narrowed)


def _pluck(claims: dict[str, Any], dotted: str) -> Any:
    current: Any = claims
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


class OidcVerifier:
    """Validates bearer JWTs against the IdP's JWKS, with a last-known-good cache."""

    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        self.issuer, jwks_uri = discover_jwks_uri(settings.issuer)
        self._jwks = PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=settings.jwks_ttl_seconds)

    def _signing_key(self, token: str) -> Any:
        return self._jwks.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=self.settings.algorithms,
                audience=self.settings.audience,
                issuer=self.issuer,
                leeway=self.settings.leeway_seconds,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
            ) from exc
        tenant = _pluck(claims, self.settings.tenant_claim)
        if not isinstance(tenant, str) or not tenant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"token has no tenant claim at {self.settings.tenant_claim!r}",
            )
        roles = _as_role_list(_pluck(claims, self.settings.role_claim))
        # Same normalization as roles: an IdP may emit groups as a list or as a
        # space-delimited string, and a bare string iterated per-character would
        # produce single-letter "audiences" that match nothing.
        audiences = (
            _as_role_list(_pluck(claims, self.settings.acl_claim))
            if self.settings.acl_claim
            else []
        )
        return Principal(
            subject=str(claims["sub"]),
            tenant=tenant_to_uuid(tenant),
            roles=frozenset(roles),
            acl_keys=frozenset(audiences) | {PUBLIC_ACL},
        )


# Roles, most to least privileged. Higher roles imply the checks lower roles pass.
ROLES = ("admin", "signing_authority", "reviewer", "estimator")

_bearer = HTTPBearer(auto_error=False)


def _verifier(request: Request) -> OidcVerifier | None:
    return getattr(request.app.state, "oidc_verifier", None)


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """The authenticated principal. In single-tenant (auth-disabled) mode this is a
    synthetic admin bound to the default tenant, preserving pre-S10 behavior."""
    verifier = _verifier(request)
    if verifier is None:
        from estimo_api.tenancy import DEFAULT_TENANT

        # Single-tenant open mode: a synthetic admin. The ACL entitlement is NOT
        # widened along with the roles — ACL keys model the SOURCE system's
        # permissions (who may read a restricted Confluence space), and Estimo's
        # users are a superset of that population even when Estimo itself is open.
        return Principal(subject="local", tenant=DEFAULT_TENANT, roles=frozenset(ROLES))
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verifier.verify(credentials.credentials)


def require_roles(*needed: str) -> Any:
    """Dependency factory: passes when the principal holds ANY of the named roles."""

    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not set(needed) & principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of roles: {', '.join(needed)}",
            )
        return principal

    return dependency


# Role groups (higher roles are allowed everywhere a lower one is). Reused as router-
# and route-level dependencies.
require_estimator = require_roles("estimator", "reviewer", "signing_authority", "admin")
require_reviewer = require_roles("reviewer", "signing_authority", "admin")
require_signing = require_roles("signing_authority", "admin")
require_admin = require_roles("admin")
