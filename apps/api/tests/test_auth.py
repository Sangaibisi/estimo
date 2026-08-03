"""S10-1: OIDC bearer auth + role model. Uses a local RSA key + a stub JWKS so no
real IdP is needed; the verifier's discovery + JWKS fetch are monkeypatched."""

import datetime as dt
import json
from collections.abc import AsyncIterator

import httpx
import jwt
import pytest
from _helpers import make_settings
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from estimo_api.auth import AuthSettings, OidcVerifier
from estimo_api.main import create_app

pytestmark = pytest.mark.db

ISSUER = "https://idp.test/realms/estimo"
AUDIENCE = "estimo-api"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key"


def _jwks() -> dict[str, object]:
    pub = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
    pub["kid"] = _KID
    pub["alg"] = "RS256"
    return {"keys": [pub]}


def _token(*, roles: list[str], tenant: str | None = "tenant-a", sub: str = "u1") -> str:
    now = dt.datetime.now(dt.UTC)
    claims: dict[str, object] = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + dt.timedelta(minutes=5),
        "realm_access": {"roles": roles},
    }
    if tenant is not None:
        claims["tenant"] = tenant
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": _KID})


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(issuer=ISSUER, audience=AUDIENCE)


@pytest.fixture(autouse=True)
def _stub_oidc(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass network: discovery returns our issuer/jwks_uri; PyJWKClient serves our key.
    def fake_init(self: OidcVerifier, settings: AuthSettings) -> None:
        self.settings = settings
        self.issuer = ISSUER

        class _Stub:
            def get_signing_key_from_jwt(self, token: str) -> object:
                class _K:
                    key = _KEY.public_key()

                return _K()

        self._jwks = _Stub()  # type: ignore[assignment]

    monkeypatch.setattr(OidcVerifier, "__init__", fake_init)

    # The MCP server also resolves the JWKS at startup; stub both to avoid a network
    # call to the fake issuer (the REST tests don't exercise /mcp auth itself).
    import estimo_api.mcp_server as mcp_module

    monkeypatch.setattr(mcp_module, "discover_jwks_uri", lambda issuer: (ISSUER, f"{ISSUER}/jwks"))
    monkeypatch.setattr(mcp_module, "JWTVerifier", lambda **kwargs: None)


@pytest.fixture
async def client(
    database_url: str, auth_settings: AuthSettings, clean_tables: None
) -> AsyncIterator[httpx.AsyncClient]:
    settings = make_settings(database_url)
    settings.auth = auth_settings
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_no_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/estimates")
    assert response.status_code == 401


async def test_estimator_token_reads_but_cannot_admin(client: httpx.AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token(roles=['estimator'])}"}
    assert (await client.get("/v1/estimates", headers=headers)).status_code == 200
    # Creating a connection needs admin.
    denied = await client.post(
        "/v1/connections",
        headers=headers,
        json={"kind": "git", "name": "x", "base_url": "https://x", "config": {}},
    )
    assert denied.status_code == 403


async def test_admin_token_may_admin(client: httpx.AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token(roles=['admin'])}"}
    created = await client.post(
        "/v1/connections",
        headers=headers,
        json={"kind": "git", "name": "auth-conn", "base_url": "https://x", "config": {}},
    )
    assert created.status_code == 201


async def test_token_without_tenant_claim_is_403(client: httpx.AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token(roles=['admin'], tenant=None)}"}
    assert (await client.get("/v1/estimates", headers=headers)).status_code == 403


async def test_health_is_open_without_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).status_code == 200


def test_expired_token_rejected(auth_settings: AuthSettings) -> None:
    verifier = OidcVerifier(auth_settings)
    now = dt.datetime.now(dt.UTC)
    expired = jwt.encode(
        {
            "sub": "u",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now - dt.timedelta(hours=1),
            "exp": now - dt.timedelta(minutes=1),
            "tenant": "t",
            "realm_access": {"roles": ["admin"]},
        },
        _KEY,
        algorithm="RS256",
        headers={"kid": _KID},
    )
    with pytest.raises(Exception):  # noqa: B017 - HTTPException(401)
        verifier.verify(expired)


def test_hs256_token_rejected_alg_confusion(auth_settings: AuthSettings) -> None:
    """An HS256-headed token must not validate against the RS256 allow-list
    (alg-confusion defense). Hand-crafted because PyJWT refuses to *encode* an
    asymmetric key as an HMAC secret — the decode-side allow-list is the real guard."""
    import base64
    import hashlib
    import hmac

    verifier = OidcVerifier(auth_settings)
    pub_pem = _KEY.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": _KID}).encode())
    body = _b64(json.dumps({"sub": "u", "iss": ISSUER, "aud": AUDIENCE, "tenant": "t"}).encode())
    signing_input = f"{header}.{body}".encode()
    sig = _b64(hmac.new(pub_pem, signing_input, hashlib.sha256).digest())
    forged = f"{header}.{body}.{sig}"

    with pytest.raises(Exception):  # noqa: B017
        verifier.verify(forged)


def test_role_claim_accepts_space_delimited_string(auth_settings: AuthSettings) -> None:
    """A space-delimited role/scope string must map to distinct roles, not chars."""
    from estimo_api.auth import _as_role_list

    assert set(_as_role_list("estimator reviewer")) == {"estimator", "reviewer"}
    assert _as_role_list(["admin"]) == ["admin"]
    assert _as_role_list(None) == []
    assert _as_role_list(42) == []  # non-iterable, non-string → empty, never a crash


def test_tenant_string_folds_to_stable_uuid() -> None:
    from estimo_api.auth import tenant_to_uuid

    a = tenant_to_uuid("acme")
    b = tenant_to_uuid("acme")
    c = tenant_to_uuid("globex")
    assert a == b and a != c
    # A real UUID passes through unchanged.
    assert tenant_to_uuid("11111111-1111-1111-1111-111111111111") == (
        "11111111-1111-1111-1111-111111111111"
    )
