# Eforge

**Evidence-linked effort estimation.** Eforge turns a customer's business requirements
document (BRD) into an auditable **Basis-of-Estimate draft** — requirement decomposition,
clarification questions, impacted-module analysis and calibrated effort ranges — grounded
in three things no generic AI tool has: **your codebase, your wiki know-how, and your own
estimate-vs-actual history.** Always reviewed and signed by humans.

> 📍 **Status: research & foundation phase (pre-code).**
> The founding research dossier lives in [docs/RESEARCH.md](docs/RESEARCH.md);
> the build plan in [docs/ROADMAP.md](docs/ROADMAP.md).

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
   stable requirement IDs. Turkish-first, multilingual by design.
2. **Decompose** — ontology-guided breakdown into work items (telco: eTOM/SID-aware).
3. **Gate** — ambiguity detection; unclear items get *clarification questions*, not numbers.
4. **Ground** — per-item agents pull evidence: code graph traversal, hybrid wiki search,
   nearest historical analogies from the estimate ledger.
5. **Estimate** — three-point effort ranges with assumptions, risks and confidence tied to
   the cone of uncertainty; every line carries evidence links.
6. **Review & sign** — humans estimate independently *before* seeing the AI draft
   (anchoring protection), then review, edit and sign line by line. Edits and eventual
   actuals feed the calibration loop.

All model calls go through an **OpenAI-compatible gateway (LiteLLM)** — model-agnostic,
self-host friendly, no provider SDKs anywhere in the codebase.

## Product laws

Eforge never shows a magic number. The full list is in
[docs/PRINCIPLES.md](docs/PRINCIPLES.md) — highlights:

- Ranges, never point estimates. No estimate without an evidence link.
- Questions before numbers: un-clarified requirements are not estimated.
- Independent human estimate first; AI draft second. Customer budget/deadline anchors are
  quarantined from estimation prompts.
- Every AI-drafted line requires a human signature before it becomes a conclusion.

## Documentation map

| Document | What it is |
|---|---|
| [docs/RESEARCH.md](docs/RESEARCH.md) | Founding research dossier (market, evidence, architecture, telco, OSS) — Turkish |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Reference architecture & tech choices |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Trackable sprint roadmap (single source of truth for plan & progress) |
| [docs/PRINCIPLES.md](docs/PRINCIPLES.md) | Evidence-derived product laws |
| [docs/UI-VISION.md](docs/UI-VISION.md) | UI vision brief feeding the design-system work |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Domain vocabulary (BRD, BoE, ledger, …) |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [AGENTS.md](AGENTS.md) | Canonical guide for AI coding agents (and humans) working in this repo |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) | How to contribute · security & data-handling policy |

## License

[Apache-2.0](LICENSE) © 2026 Emrullah Yıldırım
