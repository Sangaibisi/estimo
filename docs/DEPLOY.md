# Deploying Estimo

Estimo ships as OCI images (ADR-0006). Three supported paths, easiest first.

## 1. From source / single-tenant — `docker compose`

The compose file **builds from the working tree** (`estimo-api:local`,
`estimo-web:local`) — no registry, no release tags, and none of the repo's release
automation is involved. Cloning the repo inside your company network is a complete
deployment story:

```bash
cp .env.example .env          # then edit gateway + (optional) auth values
docker compose up --build -d  # db + migrate + api + web, built from this checkout
```

- API on `http://localhost:8000`, web on `http://localhost:3000`.
- Runs **open in single-tenant mode** — no OIDC required. Every row belongs to the
  implicit DEFAULT_TENANT.
- Point the gateway at your real endpoint before first start: in `.env` set
  `ESTIMO_GATEWAY__BASE_URL` (your LiteLLM or any OpenAI-compatible endpoint),
  `ESTIMO_GATEWAY__API_KEY`, and `ESTIMO_GATEWAY__PROFILES` (the `.env.example`
  values target the `--profile mock` stub LLM, which is for development only).
- Upgrades are `git pull && docker compose up --build -d` — the one-shot `migrate`
  service brings the schema to head before the API starts.
- Optional profiles: `--profile mock` (a stub LLM for smoke tests),
  `--profile observability` (self-hosted Langfuse — see its resource note).

### Where is everything configured?

Almost everything in the product (ADR-0008): the environment supplies *bootstrap
defaults*, and what an admin saves in the panel overrides it per field, immediately.

| What | Where |
|---|---|
| LLM gateway URL, API key, stage→model profiles, timeouts | **Admin → Model gateway** (editable form + one-click round-trip test). `ESTIMO_GATEWAY__*` env vars are the bootstrap defaults underneath |
| Bitbucket / GitHub / GitLab / Confluence / Jira integrations | **Admin → Connections** (kind, base URL, config, ACL keys, and the credential itself — sealed into the DB; or the *name* of an env var if you prefer the env lane) |
| Secret sealing | Set `ESTIMO_SECRET_KEY` (`openssl rand -hex 32`) so panel-entered secrets are **encrypted** at rest; without it they are stored `plain:`-prefixed and the panel shows a warning |
| OIDC / roles / tenancy | `ESTIMO_AUTH__*` env vars — deliberately env-only: a bad save here would lock every admin out of the panel that could fix it. Current mode shown under Admin → Runtime & authentication |
| Database | `ESTIMO_DATABASE_URL` (+ `ESTIMO_OWNER_DATABASE_URL` for multi-tenant system paths) — env-only bootstrap |
| Everything at a glance | `GET /v1/system` (admin-only, redacted — booleans for secrets, never values) |

## 2. Kubernetes / BYOC — Helm

```bash
helm install estimo infra/helm/estimo \
  --set image.tag=<sha-or-semver> \
  --set web.apiUrl=https://estimo.example.com/api
```

BYO managed Postgres and your own IdP (multi-tenant — note the **two** URLs):

```bash
helm install estimo infra/helm/estimo \
  --set postgres.bundled=false \
  --set database.url='postgresql+asyncpg://estimo_app:<pw>@db:5432/estimo' \
  --set database.migrationUrl='postgresql+asyncpg://estimo:<owner-pw>@db:5432/estimo' \
  --set database.appRolePassword='<pw>' \
  --set auth.issuer=https://idp.example/realms/acme \
  --set auth.audience=estimo-api \
  --set gateway.baseUrl=https://litellm.internal/v1 \
  --set gateway.existingSecret=estimo-gateway
```

`database.url` is what the API runs as (**`estimo_app`** — NOSUPERUSER, so RLS binds);
`database.migrationUrl` is the owner that runs Alembic (needs `CREATE ROLE` and bypasses
RLS by design). The migration runs as an **init container** on the API pod, so it works
with the bundled StatefulSet too. Optionally set `database.ownerUrl` to give the
cross-tenant system paths (startup janitor, webhook lookup) an RLS-exempt connection.

Secret material (DB passwords, gateway API key) belongs in `existingSecret`s, never in
`values.yaml`. The bundled Postgres password is generated once and **reused across
upgrades** (a regenerated password would break auth against the persisted volume).

## 3. Multi-tenant (SaaS)

Two things must be set (ADR-0007):

1. **OIDC** — set `ESTIMO_AUTH__ISSUER` / `ESTIMO_AUTH__AUDIENCE` (and the role/tenant
   claim paths) to the identity provider. Callers present a bearer access token; the
   `tenant` claim scopes every request.
2. **The RLS runtime role** — point `ESTIMO_DATABASE_URL` at the NOSUPERUSER
   `estimo_app` role, **not** the owner (a superuser bypasses RLS entirely):

   ```
   ESTIMO_DATABASE_URL=postgresql+asyncpg://estimo_app:<pw>@db:5432/estimo
   ```

   The migration creates `estimo_app`; set its password out-of-band or via
   `ESTIMO_APP_ROLE_PASSWORD` on the migration environment.

   **Verify the app-role connection over TCP** (`psql -h <host> -U estimo_app`) — the
   role authenticates with scram, unlike the trust-socket owner; a socket test can
   falsely pass while isolation is off.

### Air-gapped

Mirror `ghcr.io/sangaibisi/estimo-api` and `estimo-web` into the internal registry, set
`image.registry`, and configure the gateway to an on-prem open-weight model endpoint
(the OpenAI-compatible protocol is all Estimo requires — ADR-0001).

## Roles

`estimator` < `reviewer` < `signing_authority` < `admin`. Map your IdP groups to these
via the token's role claim (`ESTIMO_AUTH__ROLE_CLAIM`). Reads and estimator actions need
an estimator; sign-off needs a signing authority; connectors/admin need an admin.

## Source-system audiences (`ESTIMO_AUTH__ACL_CLAIM`)

Roles say what a caller may *do* in Estimo. They say nothing about what the caller may
*read in Confluence* — and Estimo indexes content whose permissions belong to the source
system. Those permissions travel with each chunk as `acl_keys`, written by the connector
(a Confluence page's effective restrictions, or the connection's declared default).

`ESTIMO_AUTH__ACL_CLAIM` is the dotted path to the token claim carrying the caller's own
audiences, in the same vocabulary your connectors write. Set it to the claim holding the
IdP group ids you used as `acl_keys` (`groups` on Okta/Entra, `realm_access.roles` or a
dedicated claim on Keycloak).

**Leaving it unset is safe but restrictive.** Estimo can then attribute no audience to
anyone, so ACL-filtered surfaces serve only content keyed `public`. It never falls back
to serving everything: a pre-filter that cannot identify the reader must show less, not
more. The same applies in single-tenant open mode — the synthetic local principal holds
every *role* but no extra audience, because your Estimo users are a superset of the
people allowed to read a restricted space.

Concretely, `POST /v1/canonical` treats the request body's `acl_keys` as a *narrowing*
preference over the caller's own audiences, never as a grant, and approving a canonical
page can only narrow the audience its sources share.

## Model Context Protocol (MCP)

The API mounts an MCP server at `/mcp` (streamable HTTP) exposing read tools
(`list_estimates`, `get_estimate_lines`, `get_decomposition`). When OIDC is configured
the endpoint is an OAuth2 **resource server** validating the same bearer tokens as the
REST API, and each tool pins the caller's tenant from the token before querying — so
MCP clients see exactly their own tenant's data. With auth disabled it runs open on the
default tenant, matching the REST API.
