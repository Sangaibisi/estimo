# Changelog

All notable changes to Estimo are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/) once code ships.
Until the first code release, entries track documentation and foundation milestones.

## [Unreleased]

### Added
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

### Changed
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
