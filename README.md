# Estimo

**Evidence-linked effort estimation.** Estimo turns a customer's business requirements
document (BRD) into an auditable **Basis-of-Estimate draft** — requirement decomposition,
clarification questions, impacted-module analysis and calibrated effort ranges — grounded
in three things no generic AI tool has: **your codebase, your wiki know-how, and your own
estimate-vs-actual history.** Always reviewed and signed by humans.

> 📍 **Status: the S0–S10 build is complete and the flow runs end to end** — upload a
> Turkish BRD, answer the clarification gate, record your own band, reveal the AI draft,
> sign, export the `.docx`. What has *not* happened yet is field validation: the
> calibration numbers come from a 15-row synthetic seed ledger, and no pilot has run
> against real delivery data. See [docs/ROADMAP.md](docs/ROADMAP.md) for exactly what is
> done, what is deferred, and what needs a human decision; the founding research dossier
> is [docs/RESEARCH.md](docs/RESEARCH.md).

**Why "Estimo"?** From the Latin *aestimo* — "I estimate, I appraise." One word, one
job: turning requirements into estimates you can defend line by line.

## Quick start

Containers are the only supported runtime ([ADR-0006](docs/adr/0006-fully-containerized.md)).

```bash
git clone https://github.com/Sangaibisi/estimo.git && cd estimo
cp .env.dev.example .env                       # demo lane: the stub LLM in this repo
docker compose --profile mock up --build
```

For a real deployment the file and the command are different — `cp .env.example .env`
and `docker compose up --build -d`, which starts db + migrate + api + web and nothing
else. The model gateway is not in that file: the API boots without one and you point it
at your endpoint from **Admin → Model gateway** ([ADR-0008](docs/adr/0008-runtime-config-in-db.md)).
See [docs/DEPLOY.md](docs/DEPLOY.md).

The web app comes up on <http://localhost:3000> and the API on <http://localhost:8000>
(OpenAPI at `/docs`), both bound to loopback. A `migrate` service runs Alembic to head
before the API starts.

Two things to know before you read anything into the output:

- **`--profile mock` is what makes that command work out of the box.**
  `.env.dev.example` points `ESTIMO_GATEWAY__BASE_URL` at a stub gateway that returns
  canned responses, and that stub only runs under the `mock` profile. Parsing,
  decomposition and the question gate are deterministic and need no model at all, but
  effort bands do — so nothing this lane produces is an estimate anyone should read.
  For that, use `.env.example` with a real LiteLLM endpoint and drop the profile flag.
- **A default install is unauthenticated and single-tenant.** Leave `ESTIMO_AUTH__ISSUER`
  empty and every endpoint is open and every request runs as the default tenant. Set an
  OIDC issuer — and connect as the `estimo_app` role, not the owner — before exposing it
  to anyone ([ADR-0007](docs/adr/0007-multitenant-auth.md)).

Four synthetic Turkish BRDs live in `fixtures/brd/` — upload one to see the whole flow
without touching customer material. Real BRDs must never enter this repo ([SECURITY.md](SECURITY.md)).

For Kubernetes, `infra/helm/estimo/` deploys the same images; `helm install` prints the
auth, database and gateway posture it is about to give you.

## Why

Software vendors — telco BSS/OSS vendors first, where this pain is sharpest — burn days of
their most senior people (business analyst, dev lead, solution architect) producing a draft
effort estimate for every incoming BRD. Our research (Aug 2026, fully sourced in the dossier)
found that:

- **No existing product combines the four corners** — customer BRD + the org's source code +
  wiki domain knowledge + historical estimate-vs-actuals — into one grounded draft estimate.
  Closest players hold at most two corners.
- **Raw LLM guesses don't work** (a controlled experiment measured ~16% accuracy for one
  commercial tool). What works: **analogy retrieval from your own history** (+59% MAE
  improvement in published research) and **ranges calibrated on your actuals** — human experts'
  90% intervals only capture reality 60–70% of the time, so calibration is beatable.
- The moat is therefore **not retrieval** (platforms are commoditizing code+wiki Q&A) but the
  **workflow + the estimate↔actual ledger** that compounds with every delivered project.

## How it works

1. **Parse** — structural extraction of the BRD (headings, tables, requirement lists) with
   stable requirement IDs. Multilingual by design — Turkish input is first-class, since
   the first target market is Turkey.
2. **Decompose** — ontology-guided breakdown into work items (telco: eTOM/SID-aware).
3. **Gate** — ambiguity detection; unclear items get *clarification questions*, not numbers.
4. **Ground** — per-item agents pull evidence: code graph traversal, hybrid wiki search,
   nearest historical analogies from the estimate ledger.
5. **Estimate** — three-point effort ranges with assumptions, risks and confidence tied to
   the cone of uncertainty; every line carries evidence links.
6. **Review & sign** — humans estimate independently *before* seeing the AI draft
   (anchoring protection), then review, edit and sign line by line. Edits and eventual
   actuals feed the calibration loop.

All model calls go through an **OpenAI-compatible gateway (LiteLLM)** — model-agnostic and
self-host friendly. `packages/gateway` is the only package that talks to a model at all,
and it does so through the OpenAI *protocol* client pointed at your gateway; no vendor
binding and no hardcoded model name exists anywhere else
([ADR-0001](docs/adr/0001-litellm-gateway-only.md)).

## Product laws

Estimo never shows a magic number. The full list is in
[docs/PRINCIPLES.md](docs/PRINCIPLES.md) — highlights:

- Ranges, never point estimates. No estimate without an evidence link.
- Questions before numbers: un-clarified requirements are not estimated.
- Independent human estimate first; AI draft second. Customer budget/deadline anchors are
  quarantined from estimation prompts.
- Every AI-drafted line requires a human signature before it becomes a conclusion.

## Documentation map

| Document | What it is |
|---|---|
| [docs/RESEARCH.md](docs/RESEARCH.md) | Founding research dossier (market, evidence, architecture, telco, OSS) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Reference architecture & tech choices |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Trackable sprint roadmap (single source of truth for plan & progress) |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Installing Estimo: compose, Helm/BYOC, air-gapped notes |
| [docs/PRINCIPLES.md](docs/PRINCIPLES.md) | Evidence-derived product laws |
| [docs/UI-VISION.md](docs/UI-VISION.md) | UI vision brief feeding the design-system work |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Domain vocabulary (BRD, BoE, ledger, …) |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [AGENTS.md](AGENTS.md) | Canonical guide for AI coding agents (and humans) working in this repo |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) | How to contribute · security & data-handling policy |

## License

[Apache-2.0](LICENSE) © 2026 Emrullah Yıldırım
