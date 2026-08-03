# ADR-0007: Multi-tenant isolation via RLS + provider-agnostic OIDC auth

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

S10 turns Estimo from a single-tenant deployment into a product that can serve multiple
customers from one installation (SaaS) while still supporting single-tenant VPC / BYOC /
air-gapped modes (ADR-0006). Two cross-cutting concerns must be decided once, centrally:
**who the caller is** (authN/Z) and **which tenant's data they may touch** (isolation).
Both were web-verified against current (2026) practice before implementation.

## Decision

### Authentication — OIDC bearer tokens, provider-agnostic

- The customer points Estimo at **their own** OIDC IdP (Keycloak / Entra / Okta / …).
  Estimo validates the incoming `Authorization: Bearer` **access token**; it never runs
  a login flow or ships an IdP.
- **Library: PyJWT + `PyJWKClient`** (FastAPI's recommended JWT stack; handles JWKS
  fetch/cache/rotation). **`python-jose` is banned** (abandoned, unpatched CVEs). PyJWT
  is a JOSE primitive, not a provider SDK, so it is compatible with ADR-0001's
  "no provider SDKs outside the gateway" rule.
- Hardening: algorithms pinned to an **asymmetric allow-list** (`RS256` by default —
  never `HS*`/`none`, defeating alg-confusion); `iss`/`aud`/`exp`/`sub` required and
  validated; small clock-skew leeway; the JWKS client keeps a last-known-good key set so
  a transient IdP blip cannot cause a permanent auth outage (PyJWT #1162).
- Every IdP collapses to four env values: `ESTIMO_AUTH__ISSUER`,
  `ESTIMO_AUTH__AUDIENCE`, `ESTIMO_AUTH__ROLE_CLAIM` (dotted path, e.g.
  `realm_access.roles`), `ESTIMO_AUTH__TENANT_CLAIM`.
- **Roles:** `estimator` < `reviewer` < `signing_authority` < `admin`. Reads and
  estimator actions need an authenticated estimator; sign-off needs `signing_authority`;
  connectors/admin surfaces need `admin`. Auth is **opt-in**: with no issuer configured
  the API runs open in single-tenant mode (a synthetic admin bound to the default
  tenant), preserving pre-S10 behavior and the OSS quick-start.

### Isolation — PostgreSQL Row-Level Security as the backstop

- Every tenant-scoped table carries a NOT NULL `tenant_id` and is under `ENABLE` +
  `FORCE ROW LEVEL SECURITY` with a policy keyed on the `app.current_tenant` GUC.
- The API sets the tenant **per transaction** via
  `set_config('app.current_tenant', :tenant, true)` (bind parameter, transaction-local —
  Postgres clears it on commit/rollback, so it cannot leak across pooled connections the
  way a session-scoped `SET` would). Because endpoints commit several times per request,
  the GUC is re-applied on every `after_begin` from a request-scoped `ContextVar`.
- **The runtime DB role `estimo_app` is `NOSUPERUSER NOBYPASSRLS`.** A superuser bypasses
  RLS entirely, so a multi-tenant deployment MUST set `ESTIMO_DATABASE_URL` to connect as
  `estimo_app`; migrations run as the owner/superuser and bypass RLS by design. The tenant
  claim (any string) is folded to a stable UUID (`uuid5`), and a well-known
  all-zeros DEFAULT_TENANT owns every pre-existing row so single-tenant deployments keep
  working with no data migration.
- RLS is **defense-in-depth**, not the only control: it is the database-enforced backstop
  under the application's own tenant scoping.

## Consequences

- Isolation is enforced by Postgres, proven by a test that connects as `estimo_app` and
  shows cross-tenant reads return nothing and cross-tenant writes are refused.
- **Operational trap (mirrors the pg_hba lesson):** the `estimo_app` role authenticates
  over TCP with a password (scram); it is not the trust-socket owner. Verify the app-role
  connection with `-h` (TCP), never the unix socket, or a false "it works" hides the
  isolation gap.
- **Unique keys are tenant-composite.** RLS restricts row *visibility*, but Postgres
  evaluates unique indexes across all rows regardless of policy — a global unique key
  would let one tenant's write collide with (or, via `ON CONFLICT`, overwrite) another
  tenant's row and would leak existence. Migration `0010` makes every such key composite
  with `tenant_id` (`connections.name`, `canonical_pages.topic`,
  `knowledge_chunks(source_type, source_ref)`, `ledger_entries.origin_ref`).
- **Cross-tenant system paths** (the startup interrupted-run janitor and the webhook
  receiver's connection lookup by opaque UUID) use an optional owner connection
  (`ESTIMO_OWNER_DATABASE_URL`); unset, they fall back to the app connection, which is
  correct in single-tenant. The sync trigger additionally self-heals orphaned `running`
  rows older than an hour, so a crash can never wedge a tenant's syncs.
- **Known residual (follow-up, flagged in code):** the web SPA does not yet run an OIDC
  login flow (it assumes single-tenant/open mode). It does not block single-tenant use
  or the S10 exit gate.
