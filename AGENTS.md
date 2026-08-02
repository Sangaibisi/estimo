# AGENTS.md — Canonical Guide for Working in This Repo

This file is the single entry point for **AI coding agents and human contributors**.
If you are an agent picking up work here: read this file fully, then read
[docs/ROADMAP.md](docs/ROADMAP.md) to find what to build next. When any other document
conflicts with this one, this one wins; fix the other document in the same PR.

## 1. What Estimo is (context in 60 seconds)

Estimo turns a customer BRD (business requirements document, `.docx`, Turkish-first) into an
**auditable Basis-of-Estimate (BoE) draft** for software vendors: requirement decomposition →
ambiguity gate with clarification questions → evidence grounding (code graph, wiki retrieval,
historical analogies) → three-point effort ranges with assumptions/risks → human review and
line-by-line sign-off → calibration loop against actuals.

Everything is justified by the founding research in [docs/RESEARCH.md](docs/RESEARCH.md)
(Turkish). The condensed reference architecture is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The non-negotiable product behaviors are [docs/PRINCIPLES.md](docs/PRINCIPLES.md).
Terminology: [docs/GLOSSARY.md](docs/GLOSSARY.md).

## 2. Golden rules (in priority order)

1. **No real customer data. Ever.** No real BRDs, customer names, wiki exports, code
   snippets from employers, or estimate spreadsheets in the repo, in fixtures, in tests, in
   issues, or in commit messages. Only synthetic or irreversibly sanitized fixtures
   (see [SECURITY.md](SECURITY.md)). If in doubt, it does not get committed.
2. **Model access only through the gateway.** All LLM/embedding/rerank calls go through an
   OpenAI-compatible endpoint (LiteLLM at deployments). Never import a provider SDK
   (`anthropic`, `openai`'s provider-specific extras, `google-genai`, …) outside the single
   gateway client module. Never hardcode a model name outside configuration.
   See [ADR-0001](docs/adr/0001-litellm-gateway-only.md).
3. **Product laws are law.** Anything user-facing must respect
   [docs/PRINCIPLES.md](docs/PRINCIPLES.md): ranges not points, evidence links on every
   estimate line, questions before numbers, independent-first review flow, no verbalized
   confidence. A PR that violates a principle is wrong even if the code is beautiful.
4. **Docs are single-source-of-truth, and stale docs are bugs.** The plan lives ONLY in
   `docs/ROADMAP.md`; architecture ONLY in `docs/ARCHITECTURE.md` + ADRs; changes ONLY in
   `CHANGELOG.md`. Do not create new planning/status/summary documents (`PLAN.md`,
   `NOTES.md`, `TODO.md`, session reports, …) — update the canonical files instead, and
   delete anything you make obsolete. If you find drift between code and docs, fixing it is
   part of your task, not optional.
5. **Prompts are versioned artifacts.** Estimation behavior is prompt-sensitive (see
   research §3). Prompts live under `packages/*/prompts/` as files with semantic version
   headers — never inline in code. Any prompt or model-routing change is a behavior change:
   it requires an eval run (see §6) and a CHANGELOG entry.
6. **Roadmap discipline.** When you complete a roadmap item, tick its checkbox in
   `docs/ROADMAP.md` **in the same PR** and update the sprint status line. Never re-scope,
   split, or delete a roadmap item silently — propose the change in the PR description.
7. **Tests and evals gate merges.** Code without tests doesn't merge. Estimation-pipeline
   changes without eval evidence don't merge. Failing CI is never "flaky, ignore".
8. **Language policy: English everywhere.** Code, identifiers, comments, commit
   messages, PRs, and **all documentation** are English — the product targets a global
   audience. Product UI default locale is English (`en`); Turkish (`tr`) is the first
   localization because the first target market is Turkey. Turkish appears in the repo
   **only as data**: synthetic BRD fixtures, retrieval benchmarks, and `tr` localization
   templates (incoming customer BRDs are Turkish — that is an input-handling requirement,
   not a documentation language). The maintainer converses in Turkish — mirror them in
   conversation; repo artifacts stay English.
9. **Security posture.** Secrets only via environment (`.env` is gitignored;
   `.env.example` documents keys). Pin dependency versions for anything touching the
   supply chain (the gateway client especially — see research §5.4). New third-party
   dependencies require a license check: MIT/Apache-2.0/BSD are fine; AGPL/SSPL/BUSL/ELv2
   need an ADR and maintainer approval. Never copy code from `ee/` or `enterprise/`
   directories of open-core projects.
10. **OSS-first composition, with a credibility bar.** Do not hand-roll infrastructure
    (parsing, retrieval, orchestration, evals) that an established, license-safe OSS
    project already solves — adopt it behind an internal interface per the checklist in
    [ADR-0005](docs/adr/0005-oss-first-composition.md). Only widely recognized projects
    qualify as dependencies: de-facto standards, major-org/foundation-backed, or
    overwhelming-adoption repos. Obscure-but-clever projects are LEARN-FROM at most.
    From-scratch code is reserved for the differentiation core (decomposition, ambiguity
    gate, analog selection, calibration, BoE workflow).

## 3. Branch topology & workflow

- **Trunk-based.** `main` is protected: always green, linear history, squash-merge only.
  No long-lived `develop` branch.
- Branch names: `feat/<scope>-<slug>`, `fix/<scope>-<slug>`, `docs/<slug>`,
  `chore/<slug>`, `spike/<slug>`.
  - `spike/*` branches are throwaway explorations: they may be messy, but they merge only
    after being cleaned into a proper `feat/*` (or their findings land as an ADR/doc).
- One roadmap item (or one coherent slice of it) per branch/PR. Reference the item ID
  (e.g. `S2-3`) in the PR title or body.
- Releases: tags `v0.x.y` from `main`; release automation (release-please) arrives in S1.
  Until then, version bumps and CHANGELOG promotion are manual.

### Commit convention

[Conventional Commits](https://www.conventionalcommits.org/):
`<type>(<scope>): <imperative summary>`

- Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `ci`, `build`.
- Scopes (extend as modules appear): `ingest`, `parse`, `ledger`, `decompose`,
  `questions`, `impact`, `estimate`, `calibrate`, `boe`, `review-ui`, `gateway`,
  `connectors`, `evals`, `fixtures`, `infra`, `docs`.
- Example: `feat(parse): docling-based requirement segmentation with stable IDs`

## 4. Definition of Done

A change is done when ALL of these hold:

- [ ] Code follows the module layout in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md);
      new architectural decisions have an ADR in `docs/adr/`.
- [ ] Tests exist and pass locally; estimation-behavior changes include eval results
      (golden-set comparison, before/after) in the PR description.
- [ ] No principle from `docs/PRINCIPLES.md` is violated; no real data introduced.
- [ ] Turkish UI strings externalized (no hardcoded user-facing text in components).
- [ ] `docs/ROADMAP.md` checkbox ticked / status updated; `CHANGELOG.md` `[Unreleased]`
      entry added for anything user-visible.
- [ ] No new planning docs created; any doc made stale by the change is updated or deleted.

## 5. Planned repository layout

Grow into this shape (create directories when their first real content arrives, not before):

```
estimo/
├── apps/
│   ├── api/            # FastAPI service: pipeline orchestration, review endpoints
│   └── web/            # Review UI (Türkçe-first)
├── packages/
│   ├── core/           # domain models: Requirement, WorkItem, EstimateLine, BoE, Ledger
│   ├── parse/          # BRD ingestion: docling wrapper, requirement segmentation
│   ├── knowledge/      # retrieval shelves: wiki index, code graph, canonical pages
│   ├── pipeline/       # LangGraph graph: decompose → gate → ground → estimate → critic
│   ├── calibrate/      # analog selection, range calibration, conformal intervals
│   ├── gateway/        # THE ONLY module that talks to the LLM endpoint
│   └── connectors/     # confluence/, git/, jira/ REST ingestors (S9)
├── evals/              # golden sets (synthetic), eval harness, metric definitions
├── fixtures/           # synthetic BRDs & sanitized examples (Turkish)
├── infra/              # docker-compose, helm (later)
└── docs/               # canonical documentation (see README map)
```

## 6. Evals are a first-class subsystem

- Offline: golden set of synthetic Turkish BRDs with reference decompositions and effort
  ranges lives in `evals/`; harness compares pipeline output on every estimation-affecting
  PR. Metrics: decomposition coverage, question quality (rubric), MAE/MdAE vs reference,
  interval coverage vs nominal, and **delta vs the naive baseline** (median of analogies) —
  sophisticated ≠ better is the field's classic failure; we always report against naive.
- Online (from S7): reviewer edit-distance per section, independent-vs-AI delta
  (anchoring telemetry), estimate-vs-actual calibration curves.
- Judges: judge model ≠ generator model; rubric-anchored; order-randomized; re-anchored
  periodically against human labels. Never trust a single verbalized LLM score.

## 7. How to pick up work

1. Read `docs/ROADMAP.md` → find the active sprint (status 🟡) → pick the first unchecked
   item without unmet dependencies.
2. Announce intent (issue or PR draft referencing the item ID) so work isn't duplicated.
3. Branch per §3, build per §4, respect §2 above all.
4. If the item turns out to be wrong/impossible as written, do NOT silently do something
   else — update the roadmap item in the PR with your reasoning.

## 8. Decision records

Significant choices (framework, storage, licensing of a dependency, wire contracts,
anything a future agent might relitigate) get an ADR: copy `docs/adr/TEMPLATE.md`, number
sequentially, link it from `docs/ARCHITECTURE.md`. Existing accepted ADRs:

- [0001 — All model access through an OpenAI-compatible gateway (LiteLLM)](docs/adr/0001-litellm-gateway-only.md)
- [0002 — Core runs adjacent to Atlassian; thin Forge/Rovo surface on top](docs/adr/0002-atlassian-adjacent-core.md)
- [0003 — Apache-2.0 license](docs/adr/0003-apache-2-license.md)
- [0004 — English-first product, Turkish-first input](docs/adr/0004-turkish-first-pipeline.md)
- [0005 — OSS-first composition: adopt proven components, build only the core](docs/adr/0005-oss-first-composition.md)
