# Deploying Estimo

Estimo ships as OCI images (ADR-0006). Three supported paths, easiest first.

## 1. Local / single-tenant — `docker compose`

```bash
cp .env.example .env          # then edit gateway + (optional) auth values
docker compose up -d          # db + migrate + api + web
```

- API on `http://localhost:8000`, web on `http://localhost:3000`.
- Runs **open in single-tenant mode** — no OIDC required. Every row belongs to the
  implicit DEFAULT_TENANT.
- Optional profiles: `--profile mock` (a stub LLM for smoke tests),
  `--profile observability` (self-hosted Langfuse — see its resource note).

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

## Model Context Protocol (MCP)

The API mounts an MCP server at `/mcp` (streamable HTTP) exposing read tools
(`list_estimates`, `get_estimate_lines`, `get_decomposition`). When OIDC is configured
the endpoint is an OAuth2 **resource server** validating the same bearer tokens as the
REST API, and each tool pins the caller's tenant from the token before querying — so
MCP clients see exactly their own tenant's data. With auth disabled it runs open on the
default tenant, matching the REST API.
