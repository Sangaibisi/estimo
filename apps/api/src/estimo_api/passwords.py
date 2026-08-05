"""Password hashing and session tokens for local accounts (S15-1).

No new dependency, on purpose (ADR-0005): password hashing is `hashlib.scrypt` from
the standard library — a memory-hard KDF backed by OpenSSL — and session tokens are
HS256 JWTs signed with PyJWT, which the OIDC verifier already brings in.

Two rules that are easy to get wrong and expensive to get wrong:

- The session-signing key is DERIVED from `ESTIMO_SECRET_KEY` rather than used
  directly, so the key that encrypts stored connector credentials and the key that
  signs session tokens are different bytes. Reusing one secret for two algorithms is
  how a padding oracle in one becomes a forgery in the other.
- With no `ESTIMO_SECRET_KEY` the process signs with a RANDOM per-boot key. Sessions
  then die on restart, which is the correct failure for a deployment that has not
  configured a secret: annoying in development, and impossible to mistake for
  production-ready.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import logging
import os
import secrets
from typing import Any

import jwt

logger = logging.getLogger("estimo.api.passwords")

# scrypt parameters. n=2**14 with r=8/p=1 costs ~16 MB and ~50 ms per hash on the
# machines this ships to — comfortably above the "interactive login" floor in the
# scrypt paper, and cheap enough that a login is not a denial-of-service lever.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32
_SALT_BYTES = 16

MIN_PASSWORD_LENGTH = 10
SESSION_TTL_HOURS = 12
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt$hash`, all base64url. Self-describing so the cost
    parameters can be raised later without invalidating existing hashes."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a stored hash. A malformed hash is a failed
    verification, never an exception — a corrupt row must not 500 the login route."""
    try:
        scheme, raw_n, raw_r, raw_p, raw_salt, raw_hash = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(raw_salt)
        expected = base64.urlsafe_b64decode(raw_hash)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(expected),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(derived, expected)


def password_complaint(password: str) -> str | None:
    """Why this password is unacceptable, or None. Length only, deliberately: NIST
    SP 800-63B retired composition rules because they push people toward
    `Password1!` — length is the property that actually costs an attacker."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


def derive_session_key() -> bytes:
    """The HS256 signing key: domain-separated from the storage-encryption key."""
    master = os.environ.get("ESTIMO_SECRET_KEY", "")
    if master:
        return hashlib.blake2b(
            master.encode("utf-8"), person=b"estimo-session", digest_size=32
        ).digest()
    logger.warning(
        "ESTIMO_SECRET_KEY is not set — session tokens are signed with a random "
        "per-process key, so every restart logs everyone out. Set it before this "
        "deployment carries real work."
    )
    return secrets.token_bytes(32)


def issue_session(
    key: bytes,
    *,
    user_id: str,
    tenant: str,
    role: str,
    can_sign: bool,
    token_version: int,
    ttl_hours: int = SESSION_TTL_HOURS,
) -> tuple[str, dt.datetime]:
    """A signed session token and the moment it expires.

    `tv` (token version) is what makes a stateless token revocable: it is compared
    against the user row on every request, and bumping the row's version — on a
    password change or a deactivation — invalidates every token already handed out.
    """
    now = dt.datetime.now(dt.UTC)
    expires = now + dt.timedelta(hours=ttl_hours)
    payload: dict[str, Any] = {
        "sub": user_id,
        "ten": tenant,
        "role": role,
        "sign": can_sign,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": "estimo",
    }
    return jwt.encode(payload, key, algorithm=_ALGORITHM), expires


def read_session(key: bytes, token: str) -> dict[str, Any] | None:
    """Verified claims, or None for anything that does not check out.

    The algorithm allow-list is a single symmetric algorithm and the key is ours
    alone, so an OIDC token from the customer's IdP can never be mistaken for a
    session token here (and vice versa: `alg: none` and RS256-signed inputs are
    rejected before any claim is read).
    """
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=[_ALGORITHM],
            issuer="estimo",
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.PyJWTError:
        return None
    return claims
