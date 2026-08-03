"""Sealing for secrets that live in the database (ADR-0008).

ADR-0006 kept every credential in the environment; ADR-0008 lets operators manage
runtime settings — gateway API key, connector tokens — from the Admin panel, which
means those values now rest in Postgres. This module is the single seam where they
are wrapped before storage:

- With ``ESTIMO_SECRET_KEY`` set, values are encrypted (Fernet: AES-128-CBC + HMAC,
  from the PyCA ``cryptography`` package) and stored as ``enc:<token>``.
- Without it, values are stored as ``plain:<value>`` — deliberately legible in the
  prefix so a DBA (or `/v1/system`) can see AT A GLANCE that encryption is off,
  rather than mistaking base64 for security.

The key is derived from the env string by SHA-256, so any sufficiently long random
string works (``openssl rand -hex 32``). Losing the key means re-entering secrets
in the panel — they are runtime config, not data, so that is an inconvenience and
not a loss.

Env indirection (storing the NAME of an env var) remains fully supported and is
still the strongest posture; sealing exists for deployments that chose panel
convenience with open eyes.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

MASTER_KEY_ENV = "ESTIMO_SECRET_KEY"

_ENC = "enc:"
_PLAIN = "plain:"


class SealedSecretError(Exception):
    """A stored secret could not be read back (missing/wrong master key)."""


def _fernet() -> Fernet | None:
    master = os.environ.get(MASTER_KEY_ENV)
    if not master:
        return None
    digest = hashlib.sha256(master.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encryption_available() -> bool:
    """True when ESTIMO_SECRET_KEY is set — surfaced by /v1/system as a warning
    when it is not, so 'unencrypted at rest' is a visible state, never a silent one."""
    return _fernet() is not None


def seal(value: str) -> str:
    """Wrap a secret for storage. Encrypts when the master key is present."""
    fernet = _fernet()
    if fernet is None:
        return _PLAIN + value
    return _ENC + fernet.encrypt(value.encode()).decode()


def unseal(stored: str) -> str:
    """Read a stored secret back. Raises SealedSecretError with an actionable
    message instead of leaking a cryptography traceback into a sync error."""
    if stored.startswith(_PLAIN):
        return stored[len(_PLAIN) :]
    if stored.startswith(_ENC):
        fernet = _fernet()
        if fernet is None:
            raise SealedSecretError(
                f"this secret is encrypted but {MASTER_KEY_ENV} is not set on this process"
            )
        try:
            return fernet.decrypt(stored[len(_ENC) :].encode()).decode()
        except InvalidToken as exc:
            raise SealedSecretError(
                f"stored secret does not decrypt with the current {MASTER_KEY_ENV} "
                "(key rotated? re-enter the secret in the Admin panel)"
            ) from exc
    # Pre-sealing rows cannot exist (the column ships with this module), so an
    # unprefixed value is corruption — refuse rather than guess.
    raise SealedSecretError("stored secret has no recognized seal prefix")


def is_encrypted(stored: str) -> bool:
    return stored.startswith(_ENC)
