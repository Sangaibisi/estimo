# ADR-0008: Operator settings live in the database, environment is bootstrap

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

ADR-0006 made the environment the only configuration source. That was the right
posture for a container-first project, but it failed the actual operator: Estimo's
primary deployment story became "clone the source and stand it up inside the
company", where the person configuring the LLM gateway and the Bitbucket/Confluence
integrations is using the product, not editing compose files. The maintainer's
explicit requirement: everything operational — gateway URL, API key, model profiles,
connector credentials — must be configurable from the Admin panel; only genuinely
technical bootstrap values may stay in the environment.

This reverses a security stance ADR-0006 and SECURITY.md stated plainly ("secrets
via environment only"), so the reversal is recorded here rather than done quietly.

## Decision

Operator-level runtime settings move to the database and are editable in the Admin
panel; the environment remains as bootstrap defaults and the panel overrides it
**per field**, effective immediately (no restart).

- A global `runtime_settings` table (key → JSONB document, no tenant scope, no RLS)
  holds the gateway override; `connections` gains a `secret` column for panel-entered
  credentials. Precedence: panel > environment, evaluated per field — a document that
  omits a field falls through to the env value. (The panel's form submits every field
  it displays, so in practice one save pins them all; the API contract is per field,
  which is what an operator scripting `PUT /v1/system/gateway` gets.)
- **Secrets are sealed before storage** (`estimo_core.secrets`): encrypted with
  Fernet when `ESTIMO_SECRET_KEY` is set, stored with a deliberately legible
  `plain:` prefix when not — and `/v1/system` plus the Admin panel display a
  warning in that state. No silent pseudo-security.
- **Redaction is unchanged in both directions:** secret values never serialize out
  of the API (presence booleans only, URL userinfo stripped), and arrive sealed
  before they touch a row.
- **Env-only bootstrap set (deliberately small):** database URLs, OIDC
  (`ESTIMO_AUTH__*` — a bad save there would lock every admin out of the very panel
  that could fix it), CORS origins, log level, and `ESTIMO_SECRET_KEY` itself.
- The env-var-name lane for connector credentials (`secret_env`) remains fully
  supported and is still the strongest posture; a stored secret wins over it when
  both exist.

## Consequences

- Easier: source-direct company deployments configure everything from the product;
  "save then Test gateway" verifies the actual saved config; key rotation is a
  panel action, not a fleet restart.
- Harder / given up: the database is now part of the secret perimeter — a DB dump
  contains credentials (encrypted only if `ESTIMO_SECRET_KEY` is set, so setting it
  is strongly recommended and the panel nags); config changes are no longer
  automatically captured by infra-as-code review flows.
- Multi-tenant note: `runtime_settings` is deployment-global, like the gateway it
  configures. In shared-SaaS, the `admin` role therefore means *platform operator*,
  not tenant admin — the same boundary `/v1/system` already implied.
- Revisit triggers: per-tenant gateway routing (would need tenant-scoped settings
  and per-tenant key sealing), an external secret manager integration (Vault/KMS
  would replace `ESTIMO_SECRET_KEY`), or audit requirements for config changes
  (would need a history table, not a key-value row).
