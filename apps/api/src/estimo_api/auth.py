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
    # S15-1 local accounts. `role` is the product role (platform_admin /
    # project_owner / user); `roles` above stays the capability set every existing
    # route guard reads, derived from it. `user_id` is None for OIDC and open-mode
    # callers, who have no row in `users`.
    user_id: str | None = None
    role: str | None = None
    can_sign: bool = False
    # True when this caller is a platform admin acting inside a tenant that is not
    # their own (X-Estimo-Tenant). Surfaced so audit-sensitive routes can say so.
    impersonating_tenant: bool = False


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

# Product role → the capability set every pre-S15 route guard is written against.
# A plain user gets `reviewer` as well as `estimator` on purpose: reviewer gates the
# READ side of the ledger, calibration and connections — surfaces the product is
# useless without. What separates a project owner from a user is not a capability in
# this table but the project/map write routes, which check the product role itself.
_CAPABILITIES: dict[str, frozenset[str]] = {
    "platform_admin": frozenset(ROLES),
    "project_owner": frozenset({"estimator", "reviewer"}),
    "user": frozenset({"estimator", "reviewer"}),
}
# The tenant a platform admin wants to act inside. Ignored for everyone else — a
# header is a request, and only that role's authorization turns it into a fact.
ACTING_TENANT_HEADER = "X-Estimo-Tenant"

_bearer = HTTPBearer(auto_error=False)


def capabilities_for(role: str, *, can_sign: bool) -> frozenset[str]:
    caps = _CAPABILITIES.get(role, frozenset({"estimator"}))
    return caps | {"signing_authority"} if can_sign else caps


def product_role(roles: frozenset[str]) -> str:
    """The product role implied by a legacy capability set (OIDC callers)."""
    if "admin" in roles:
        return "platform_admin"
    if "reviewer" in roles:
        return "project_owner"
    return "user"


def _verifier(request: Request) -> OidcVerifier | None:
    return getattr(request.app.state, "oidc_verifier", None)


async def _local_principal(request: Request, token: str) -> Principal | None:
    """Resolve a session token issued by THIS deployment, or None if it is not one.

    The user row is read on every request rather than trusted from the token: it is
    what makes deactivation and password changes take effect immediately instead of
    at the end of a 12-hour session.
    """
    from sqlalchemy import select

    from estimo_api.accounts_models import User
    from estimo_api.passwords import read_session

    key: bytes | None = getattr(request.app.state, "session_key", None)
    maker = getattr(request.app.state, "system_sessionmaker", None)
    if key is None or maker is None:
        return None
    claims = read_session(key, token)
    if claims is None:
        return None
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (ValueError, KeyError):
        return None
    async with maker() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active or user.token_version != claims.get("tv"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session is no longer valid — sign in again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tenant = str(user.tenant_id)
    impersonating = False
    if user.role == "platform_admin":
        requested = request.headers.get(ACTING_TENANT_HEADER)
        if requested:
            try:
                tenant = str(uuid.UUID(requested))
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{ACTING_TENANT_HEADER} must be a tenant uuid",
                ) from None
            impersonating = tenant != str(user.tenant_id)
    return Principal(
        subject=user.email,
        tenant=tenant,
        roles=capabilities_for(user.role, can_sign=user.can_sign),
        acl_keys=frozenset(user.acl_keys or []) | {PUBLIC_ACL},
        user_id=str(user.id),
        role=user.role,
        can_sign=user.can_sign,
        impersonating_tenant=impersonating,
    )


async def _deployment_is_open(request: Request) -> bool:
    """True while no account exists yet: the pre-S15 open mode.

    A deployment leaves this state the moment the first platform admin is created
    and never returns to it, so the answer is memoized once it is False. Any error
    reading the table is treated as CLOSED — a database we cannot question must not
    be the reason the API starts trusting anonymous callers.
    """
    if getattr(request.app.state, "accounts_exist", False):
        return False
    from sqlalchemy import text

    maker = getattr(request.app.state, "system_sessionmaker", None)
    if maker is None:
        return False
    try:
        async with maker() as session:
            exists = bool(
                (await session.execute(text("SELECT EXISTS (SELECT 1 FROM users)"))).scalar()
            )
    except Exception:  # noqa: BLE001 — any failure here must fail CLOSED
        logger.warning("could not read the accounts table; treating the API as closed")
        return False
    if exists:
        request.app.state.accounts_exist = True
    return not exists


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """The authenticated principal.

    Three lanes, in order: a session token issued by this deployment (local accounts,
    S15-1), an OIDC bearer from the customer's IdP (S10-1), and — only while no
    account exists at all — the historical open mode.
    """
    from estimo_api.tenancy import DEFAULT_TENANT

    if credentials is not None:
        local = await _local_principal(request, credentials.credentials)
        if local is not None:
            return local
        verifier = _verifier(request)
        if verifier is not None:
            principal = verifier.verify(credentials.credentials)
            return principal.model_copy(
                update={
                    "role": product_role(principal.roles),
                    "can_sign": "signing_authority" in principal.roles,
                }
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _verifier(request) is None and await _deployment_is_open(request):
        # Nothing configured, nobody enrolled: a synthetic admin on the default
        # tenant, preserving pre-S10 behavior. The ACL entitlement is NOT widened
        # along with the roles — ACL keys model the SOURCE system's permissions (who
        # may read a restricted Confluence space), and Estimo's users are a superset
        # of that population even when Estimo itself is open.
        return Principal(
            subject="local",
            tenant=DEFAULT_TENANT,
            roles=frozenset(ROLES),
            role="platform_admin",
            can_sign=True,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="bearer token required",
        headers={"WWW-Authenticate": "Bearer"},
    )


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


def require_product_roles(*needed: str) -> Any:
    """Dependency factory keyed on the PRODUCT role (S15-1).

    Separate from `require_roles` because the product roles are not a ladder of the
    same capabilities: a project owner outranks a user only over projects and the
    repository map, and nowhere else.
    """

    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if principal.role not in needed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of roles: {', '.join(needed)}",
            )
        return principal

    return dependency


require_platform_admin = require_product_roles("platform_admin")
# Who may create a project and draw its map.
require_project_owner = require_product_roles("platform_admin", "project_owner")
