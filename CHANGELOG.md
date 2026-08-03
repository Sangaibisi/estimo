# Changelog

All notable changes to Estimo are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/) once code ships.
Until the first code release, entries track documentation and foundation milestones.

## [Unreleased]

### Added
- **S11-8 embedding writer — retrieval is hybrid in fact, not just in the diagram.**
  Nothing in this repository had ever written an embedding: the only `.embed()` call
  embedded the *query*, so `dense_ledger_ids` filtered `embedding IS NOT NULL` against
  zero rows and RRF fused a single ranking, in every deployment, for the whole life of
  the project. `embed_pending` fills chunk and ledger vectors through the gateway
  (profile `embedding`, inert when unconfigured), running after each connector sync and
  on demand via a new `estimo-embed` CLI. Batches commit independently so a rate limit
  mid-backfill keeps the completed half; an oversized page is capped and reported rather
  than failing the batch behind it (there is no chunker yet, so a "chunk" is a whole
  page); and the model id and dimension are stored per row, so switching embedders drops
  old rows OUT of the dense leg rather than scoring them in the wrong vector space.
  The embedding pass runs *after* a sync is marked succeeded and is reported separately:
  a gateway outage must not turn a completed multi-day crawl into a failed run.
  **Unmeasured on purpose** — whether the dense leg improves Turkish ranking still needs
  a live embedding endpoint (the S3-2 shoot-out). This ships the data path, not a
  quality claim.
- **Ledger attribution (part of S11-4; the sliced curves themselves are not built).**
  `record_actual` copied `team` and `domain_tags` off the `WorkItem`, and the pipeline
  never sets either — a BRD says what to build, not who builds it — so every ledger row
  the product wrote landed with `team = NULL`. Measured on a live instance: zero of
  zero product-origin rows carried a team. That is unrecoverable data, since nobody
  reconstructs delivery attribution a year later, which is why it ships now rather than
  with the curves it enables. `POST /actuals` takes optional `team`/`domain_tags` from
  whoever closes the loop, normalized with `tr_lower` at both write paths so `Billing`
  and `billing` cannot become two slices, and `GET /v1/metrics/overview` gained an
  `attribution` block so "attribution shipped" stays distinguishable from "attribution
  arrives" — the field is optional, so silence is a real outcome and worth counting.
- **S11-3 Delphi overlay**: the estimate desk shows every panelist's band for an item as
  anonymous lines over the consensus range, with the spread and an intersect/disjoint
  verdict. Two server-side gates, each proven load-bearing by removing it and watching
  the test go red: you must have recorded your own band for that item (the panel is
  otherwise a second route to other people's numbers, past the independent-first gate),
  and at least three estimators must have recorded on it. Below either gate the block
  carries no band-shaped number at all — with two panelists a median plus your own band
  reconstructs the other person's exactly, so a "summary only" concession would leak the
  same data with extra steps. Bands sort by value and re-sort per item, so no line maps
  to a person. Moderator identity reveal is not built and the design caption promising
  it was rewritten rather than shipped as a false promise.
- **S10 authN/Z** (`apps/api/auth.py`): provider-agnostic OIDC bearer-token validation
  (PyJWT + PyJWKClient — `python-jose` banned) against the customer's own IdP, with a
  role model (`estimator` < `reviewer` < `signing_authority` < `admin`). Opt-in: with
  no issuer configured the API runs open in single-tenant mode. Hardening: asymmetric
  algorithm allow-list (no alg-confusion), `iss`/`aud`/`exp`/`sub` required, last-known-
  good JWKS fallback. Sign-off requires a signing authority; connectors/admin require
  an admin (ADR-0007).
- **S10 multi-tenant isolation** (migration `0009`): PostgreSQL Row-Level Security on
  every tenant table, keyed on a transaction-local `app.current_tenant` GUC set per
  request from the token's tenant claim; a dedicated `NOSUPERUSER NOBYPASSRLS`
  `estimo_app` runtime role. Proven by a test that connects as that role and shows
  cross-tenant reads return nothing and cross-tenant writes are refused. A well-known
  DEFAULT_TENANT preserves single-tenant deployments with no data migration.
- **S10 MCP server** (`/mcp`, FastMCP 3.x over streamable HTTP): read tools
  `list_estimates`, `get_estimate_lines`, `get_decomposition`, sharing the API's tenant
  isolation and OIDC auth.
- **S10 packaging**: a Helm chart (`infra/helm/estimo`) for Kubernetes/BYOC (bundled or
  external Postgres, migration hook, runtime-injected web API origin), a deployment
  guide (`docs/DEPLOY.md`, incl. air-gapped notes), and design notes for the Atlassian
  Forge Rovo Agent front-door (S10-4) and the optional FP/COSMIC functional-size layer
  (S10-7).
- **S9 connectors** (`packages/connectors`, migration `0007`): live knowledge from
  real sources. Confluence Cloud crawler (v2 cursor pagination, v1-only read
  restrictions mapped onto retrieval ACL keys, checkpointed CQL incremental sync,
  points-budget pacing that honors `Retry-After` and slows on
  `X-RateLimit-NearLimit`); **Bitbucket-first** git hosting (access-token auth —
  app passwords were removed upstream 2026-07-28 — repo listing via the `next`
  URL, webhook secrets with `X-Hub-Signature` HMAC verification over raw bytes)
  plus GitHub/GitLab equivalents and a plain-git fallback; repo sync clones with
  the git binary (credentials via an ephemeral `GIT_ASKPASS`, never in URLs or
  argv) and feeds the S5 index → module wikis with connection ACL and commit-time
  freshness; optional Jira pull on the post-410 `/search/jql` endpoint with
  per-site story-points field discovery.
- **S9 curation + honesty**: canonical-pages flow (LLM drafts a candidate with
  recorded provenance; only HUMAN-approved pages enter retrieval, at top
  authority 0.95), authority as a relevance tie-breaker, `is_stale` (18-month)
  staleness surfaced in the curation UI, and a mandatory ACL pre-filter
  regression test (a restricted chunk is mechanically invisible to other keys).
  Admin → Connections UI: env-indirected secrets (names only), sync status,
  webhook endpoint per connection.
- **S8 calibration loop** (`packages/estimate/loop.py`, migration `0006`): recording an
  actual turns the signed line into a first-class ledger row
  (`origin_ref = estimate://…`), applies bounded outcome feedback to the `ledger://`
  analogs that backed the line (folded into `find_analogs` ranking as a ±2-position
  nudge — retrieval similarity stays primary), and snapshots the transfer-error
  quantiles + rolling coverage per event. Design web-verified: at this ledger scale,
  event-driven full recompute beats online/streaming conformal updates; drift
  surfaces via rolling coverage, never chased silently.
- **S8 actuals entry**: `POST/GET /v1/estimates/{id}/actuals` (attach to the fully
  signed estimate of record; scope-changed actuals are stored but excluded from
  feedback and calibration) + an Actuals tab in the web UI with per-line deviation.
- **S8 honesty dashboards**: `GET /v1/metrics/overview` + `/dashboard` page — interval
  coverage vs nominal over calibration snapshots, anchoring telemetry (mean |Δ| and
  near-zero-delta share), MAE vs the naive median baseline, and DORA-style
  second-order tiles (WIP, question-revision rate, rebuild share). Every rate ships
  with its sample count; small samples are labeled, never hidden.
- **S8 observability (opt-in)**: `docker compose --profile observability up` runs a
  pinned Langfuse v4 self-host stack (web/worker + dedicated Postgres, ClickHouse,
  Redis, MinIO — upstream sizes it at ~4 cores/16 GiB); the api forwards telemetry
  events and anchoring scores via the MIT `langfuse` SDK **only when `LANGFUSE_*`
  env is set** — unset means a complete no-op.
- **S7 review UI** (`apps/web` + `apps/api` workflow endpoints): Next.js estimation
  workspace — BRD upload, requirement/question board with quality-gated answers, the
  **independent-first Estimate Desk** (the server keeps the AI band locked until the
  estimator records their own three-point band; reveal shows the delta and evidence
  chips; per-line sign-off), and Turkish BoE `.docx` export. `en` default locale with
  `tr` as the first localization; design tokens from the S0 design-system output.
- **S7 web containerization**: multi-stage `apps/web/Dockerfile` (standalone Next
  output, non-root, healthcheck), compose `web` service, and CI publish of
  `ghcr.io/sangaibisi/estimo-web` (multi-arch, SBOM + provenance). The browser-visible
  API origin is injected at **runtime** from `ESTIMO_API_URL` — never baked into the
  image at build time.

- **S6 estimation** (`packages/estimate`): analog-grounded three-point bands with
  conformal-style calibration on the ledger's **analog-transfer** error (leave-one-out
  actual/analog-median quantiles — measured leave-one-out on the 15-row synthetic seed
  ledger: **87% interval coverage at nominal 80%**, and MAE 6.35 pd against a naive
  analog-median baseline of 7.07 pd. Calibrating on per-entry estimate deviation instead
  gave 7% coverage, which is why the transfer distribution is the one used. The
  quantiles are fit in-sample on 15 rows, so these numbers demonstrate the mechanism,
  not field accuracy — see `evals/reports/2026-08-03-s6-loo-eval.md`). Cold-start priors below 8 samples (always labeled), small-item overhead
  floors, expert-recall down-weighting. The estimator refuses non-ready states
  (PRINCIPLES #3), attaches ledger://+repo://+answer:// evidence to every line,
  converts LOW-confidence impacts into discovery risks with contingency, and lets the
  gateway nudge likely only WITHIN the band (anchors redacted, PRINCIPLES #5).
  Deterministic critic (gate-leak, duplicates, spread sanity, missing cold-start
  assumption), locale-aware BoE `.docx` renderer (full professional anatomy, TR
  number formatting), `estimo-boe` and `estimo-effort-eval` CLIs, LOO eval report in
  `evals/reports/2026-08-03-s6-loo-eval.md`.
- **S5 code shelf** (`packages/code`): tree-sitter symbol graph for Java/TypeScript
  (indexer-agnostic store — SCIP loader slots in at the first real build chain), ranked
  token-budgeted repo map, deterministic module wikis (purpose/interfaces/dependencies,
  optional gateway refinement) ingested into the knowledge shelf at authority 0.7, and
  the impact worker with a confidence ladder (symbol match HIGH → import neighborhood
  MEDIUM → keyword-only LOW with an explicit discovery-effort suggestion). Turkish→
  identifier synonym bridge (taksit→installment …); every impact claim carries a
  validated `repo://…#L–L` evidence URI. Synthetic meridyen-mini fixture repo with
  known change scenarios asserted in CI.
- **S4 pipeline** (`packages/pipeline`): LangGraph state machine parse → ambiguity gate →
  clarification questions → decomposition, with an offline deterministic floor at every
  node (a down or misbehaving gateway degrades quality, never correctness). The gate
  law is mechanical: blocked requirements own no work items; human answers re-enter
  through the gate, which re-evaluates. Versioned prompt files (loader fails loudly on
  unversioned prompts; 11 Turkish few-shot examples for question generation),
  ontology-guided module attribution over the Aurora taxonomy, `estimo-pipeline`
  run/resume CLI, and the `estimo-eval` offline harness asserted in CI — first report:
  module attribution 92% vs 31% naive baseline (+62), zero gate failures, zero
  question gaps (`evals/reports/2026-08-03-s4-offline-eval.md`). Pydantic AI was
  deliberately not adopted (its own model clients would bypass ADR-0001).
- **S3 knowledge layer** (`packages/knowledge`): estimate-ledger Postgres schema
  (migration 0002) with Turkish-FTS generated tsvectors and dimension-flexible
  embeddings (model id + dim recorded per row); seed-set importer
  (`estimo-ledger-import`) implementing the LEDGER-SCHEMA contract — CSV/XLSX header
  aliases, Turkish dates/decimals, bad-row report, unknown-module review queue; hybrid
  retrieval (Turkish lexical with suffix-strip prefix matching + optional dense leg via
  the gateway, RRF fusion, ACL pre-filter on chunks); analogy cards carrying the
  outside view (estimate then vs actual, deviation). Turkish retrieval golden set
  (`evals/golden/retrieval-tr/`) asserted in CI; embedder/reranker shoot-out deferred
  to the first live gateway (ADR-0004 updated with the lexical-leg decision).
- **S2 BRD parsing** (`packages/parse`): Turkish `.docx` BRDs → stable-ID requirement
  tables via Docling's DOCX backend (slim install, no ML models — ADR-0005 scope
  discipline). Extraction ladder: explicit codes → requirement tables (acceptance
  criteria captured) → modal-verb heuristics for messy documents. Anchor quarantine
  detection (budget/deadline/analogy/effort-hint, PRINCIPLES #5), deterministic
  ambiguity pre-score with an optional gateway LLM blend that can only raise the rule
  floor, document-level open-point extraction, and the `estimo-parse` CLI. Golden eval
  in CI asserts every planted anchor/ambiguity in the fixture manifest is caught.
- **S1 skeleton (first code):** uv-workspace monorepo (Python 3.13/3.14) with
  `packages/core` (pydantic domain models that structurally enforce the product laws —
  three-point ranges, evidence-required estimate lines), `packages/gateway` (the single
  OpenAI-compatible client module: stage→profile routing, Retry-After-aware retries,
  metadata-only logging hooks), and `apps/api` (FastAPI: liveness/readiness split,
  run records on Postgres via async SQLAlchemy + Alembic, pgvector enabled in
  migration 0001).
- Fully containerized dev loop per ADR-0006: multi-stage uv Dockerfile (non-root,
  stdlib healthcheck), `compose.yaml` with healthcheck-gated migrate→api ordering and a
  `mock` profile (OpenAI-compatible mock LLM + gateway smoke check).
- CI/CD: lint/typecheck/test workflows (uv, matrix 3.13/3.14, pgvector service),
  provider-SDK and open-core path guards as tested code, multi-arch GHCR publish on
  native arm64 runners with provenance/SBOM attestations, release-please v5,
  semantic PR-title enforcement, dependency review with an ADR-0005 license denylist,
  Dependabot (actions/docker/uv) and CodeQL default setup.
- Design system artifacts under [docs/design/](docs/design/) (hi-fi screens, wireframes,
  tokens — Aurora Telecom installment scenario, light+dark, IBM Plex).
- S0 data foundation: Aurora fixture universe standard
  ([fixtures/README.md](fixtures/README.md)), estimate ledger schema v0 + seed-set import
  contract ([docs/LEDGER-SCHEMA.md](docs/LEDGER-SCHEMA.md)), in-house seed-set inventory
  template ([docs/SEED-SET-INVENTORY.md](docs/SEED-SET-INVENTORY.md)), golden-set &
  metrics design ([evals/README.md](evals/README.md)), synthetic Turkish BRD fixtures
  with planted-feature manifest ([fixtures/brd/](fixtures/brd/)).
- ARCHITECTURE: explicit **ordered indexing pipelines** section (wiki / code / ledger
  lanes + query path); git-hosting connectors named explicitly with **Bitbucket
  first-class** (roadmap S9-2, Admin → Connections).
- ADR-0006: **fully containerized delivery** — every component ships as a multi-arch OCI
  image on GHCR; `docker compose up` is the canonical dev & single-node runtime, Helm
  consumes the same images (roadmap S1-5/S1-8/S7-9 updated).
- ADR-0005: OSS-first composition — adopt proven, license-safe components behind internal
  interfaces; from-scratch code reserved for the differentiation core. Linked from
  AGENTS.md golden rules and ARCHITECTURE.md.

### Fixed
- `upsert_document` invalidated a row's embedding on **every** write. The Confluence
  lane re-ingests a 26-hour overlap window of unchanged pages on each incremental sync,
  so that would have wiped every vector in the window on each run and re-billed the
  embedder forever to recompute byte-identical text. It now invalidates only when the
  embedded text actually changed — and still does when it did, because a stale vector
  for edited text retrieves confidently against content that no longer says that.

### Security
- **`GET /v1/estimates/{id}/desk` no longer mutates.** It flipped the caller's
  `revealed` flag, wrote a `draft-revealed` event and emitted the anchoring delta —
  from a read. A link prefetch, a crawler, or anyone passing a colleague's name in the
  `estimator` query string could therefore consume that colleague's un-revealed state
  permanently (bands are immutable) and write an anchoring sample for a reveal that
  never happened to a person who never saw it, corrupting the very measurement
  PRINCIPLES #4 exists to produce. The reveal now belongs to `POST /independent`, the
  deliberate act that earns it: committing your own number is the moment anchoring
  protection ends, and the number recorded is identical. Guarded by a regression test
  verified in both directions — it fails if recording stops emitting, and it fails if
  reading starts.
- **The ACL pre-filter no longer takes its permissions from the requester.**
  `POST /v1/canonical` passed the request body's `acl_keys` straight into
  `lexical_chunk_ids`, so any reviewer could name a restricted audience, have its text
  distilled into a draft body, and read that body back from `GET /v1/canonical` — which
  returns page bodies to every reviewer in the tenant. `Principal` now carries the
  audiences Estimo can actually attribute to a caller (from `ESTIMO_AUTH__ACL_CLAIM`),
  and `clamp_acl_keys` treats a requested key list as a *narrowing preference over that
  set*, never as a grant. Unset claim, or single-tenant open mode, means public-only —
  a pre-filter that cannot identify its reader must show less, not more (SECURITY.md).
  The synthetic open-mode principal deliberately does **not** inherit every audience
  along with every role: ACL keys model the *source* system's permissions, and Estimo's
  users are a superset of who may read a restricted Confluence space.
- **Approving a canonical page can no longer widen it.** Explicit `acl_keys` overrode
  the computed source intersection outright, so text distilled from a restricted space
  could be published to a wider audience — the same widening the pre-filter prevents,
  applied at write time. Explicit keys may now only narrow. Fixing this exposed why the
  override existed: the intersection treated `public` as a constraint, so one public
  source plus one restricted source looked unpublishable when the correct audience is
  simply the restricted one. `restricting_audiences` (in `estimo_core`, shared by the
  API clamp and the publish clamp) now excludes universally-held keys, and genuinely
  disjoint audiences stay unpublishable together.
- **S10 review hardening** (adversarial review; 10 confirmed findings fixed): the MCP
  endpoint is now an OAuth2 resource server (FastMCP `JWTVerifier`) that pins the
  caller's tenant from the validated token — it was reachable unauthenticated and read
  the default tenant. Unique keys on tenant tables are composite with `tenant_id`
  (migration `0010`) so one tenant's write can no longer collide with, overwrite, or
  probe another's. Helm: the API/migration split onto the right DB roles (RLS was
  bypassed by connecting as the owner), the migration moved to an init container (the
  hook ran before the bundled Postgres existed), and the bundled password is reused
  across upgrades instead of regenerated. Cross-tenant system paths take an optional
  owner connection; the sync trigger self-heals orphaned `running` rows. Role claims
  accept a space-delimited string (a bare string was iterated per character, silently
  denying every role).
- **S9 review hardening** (adversarial review; 28 confirmed findings fixed): the ACL
  pre-filter provably never widens — Confluence connections require explicit
  `space_keys`, read restrictions resolve by walking ancestors (inheritance), and
  canonical approval publishes the intersection of its sources' ACL keys (refusing
  mixed-audience defaults). Connection names are slugged before becoming filesystem
  paths (no `../` escape). Also: one-running-sync-per-connection is DB-enforced
  (migration `0008`), interrupted runs are swept at startup, pagination follows
  `_links.next` verbatim (no cursor double-encoding), the incremental watermark uses
  real datetimes with a 26h overlap, deleted source modules are pruned from
  retrieval, and GitLab signed webhooks enforce a replay window.
- **S7 review hardening** (adversarial review; 14 confirmed findings fixed):
  independent-first now holds across the WHOLE API surface — `GET /{id}`, the build
  response and the `.docx` export withhold the draft body until every line is signed,
  and signing itself requires the signer's own revealed band. BoE drafts are
  **versioned** (migration `0005`): reveals, sign-offs and anchoring telemetry are
  bound to the draft they were recorded against, so a rebuild never inherits them,
  and rebuilding over a live draft is refused. Also: upload size limit enforced while
  streaming; `Content-Disposition` uses an ASCII slug + RFC 5987 `filename*` (no
  header injection, no non-latin-1 500s); server-reserved telemetry kinds are not
  forgeable; empty answers no longer close questions; `.dockerignore` patterns fixed
  so nested env files and Node artifacts stay out of build contexts.

### Changed
- **Doc-truth pass #2**, from scoping the S11 items against the code. The first pass fixed
  claims that were *overstated*; this one fixes claims that were *wrong*. Retrieval is
  **lexical in practice everywhere**: nothing in the repo writes an embedding — the only
  `.embed()` call embeds the query, and `upsert_document` NULLs the vector columns on every
  write — so `dense_ledger_ids` matches zero rows and RRF fuses a single ranking. There is
  also no chunker: a Confluence page becomes one `knowledge_chunks` row, so "chunk" is
  currently a misnomer for "document". ARCHITECTURE.md said otherwise in three places
  (component table, wiki lane, query path) and now says this. The S11-4 blocker recorded
  yesterday was itself wrong — `ledger_entries` has carried `team` and `domain_tags` since
  migration 0002. Added S11-8 for the missing embedding writer, split S11-6 into the docs
  site (decided against, with the reasoning) and the Marketplace assessment (blocked on the
  deferred Forge surface), and recorded the sourcing escalation found under S11-7.
- CONTRIBUTING.md told contributors "the repo is documentation-only and the only build is
  reading docs/RESEARCH.md" — ten sprints after that stopped being true. It now carries the
  real gates (uv sync, ruff, mypy, pytest, the separate npm build for `apps/web`). AGENTS.md
  named a `packages/calibrate/` that has never existed, omitted `code/` and `estimate/`,
  labelled the web app "Türkçe-first" in an English document and called the translated
  research dossier Turkish. docs/DEPLOY.md had no inbound link from any navigable page and
  is now in the README map.
- **The web UI now implements the delivered design system**, not just its colour
  tokens (`docs/design/estimo-ui.dc.html`). Ported: the full token set (surfaces,
  ink tiers, two-tier borders, status and evidence roles, shadows), both density
  modes, IBM Plex Sans/Mono/Serif self-hosted at build time, and the component
  layer (`.dt` · `.card` · `.chip` · `.btn`/`.btn.p` · `.rail-i` · `.stg` · `.ph` ·
  `.lbl`/`.num`/`.mn`). Bespoke components implemented as the design specifies them:
  **RangeBar** (three-point band with the overhanging likely marker), **EvidenceChip**
  (a third colour role), **StatusChip** where **shape carries state alongside colour**
  (circle = good, diamond = warning, square = critical), and the **StageStrip**.
  The app now has the design's chrome — sticky top bar with theme/density toggles and
  the 184px left rail — and its screens: Workspace, Reading Room, Question Board,
  **Impact Map**, Estimate Desk (with the honest closed state — never a blurred
  reveal), BoE Preview & Signature, **Ledger & Analog Search** (new,
  `GET /v1/ledger`), Calibration Dashboard, Knowledge Curation, and Admin.

#### Earlier
- Project renamed from **Eforge** to **Estimo** (briefly Lodestar) — from the Latin
  *aestimo*, "I estimate, I appraise".
- **English is now the repository's single language**: the research dossier, roadmap and
  UI vision were translated; Turkish remains as *data only* (synthetic BRD fixtures,
  retrieval benchmarks, `tr` localization templates). ADR-0004 revised to
  "English-first product, Turkish-first input"; AGENTS.md language policy updated.
- ADR-0005 gained an explicit **credibility bar**: only de-facto-standard,
  major-org-backed, or overwhelmingly adopted OSS projects qualify as dependencies.
- README is now English-only (Turkish summary section removed).

## [0.1.0] - 2026-08-03

### Added
- Founding research dossier ([docs/RESEARCH.md](docs/RESEARCH.md)): market gap analysis,
  evidence review on LLM-based effort estimation, reference architecture, telco domain
  layer, and open-source stack survey — synthesized from a 5-track parallel research run.
- Repository foundation: README, Apache-2.0 license, agent guide ([AGENTS.md](AGENTS.md)),
  contributor guide, security & data-handling policy, code of conduct.
- Product principles ([docs/PRINCIPLES.md](docs/PRINCIPLES.md)) — evidence-derived rules
  every feature must respect (ranges over points, evidence links, anchoring protection).
- Architecture reference ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) and initial ADRs
  (LiteLLM-only gateway, Atlassian-adjacent core, Apache-2.0, Turkish-first pipeline).
- Trackable sprint roadmap ([docs/ROADMAP.md](docs/ROADMAP.md)).
- UI vision brief ([docs/UI-VISION.md](docs/UI-VISION.md)) — input for the design-system pass.
