# Contributing to Estimo

Thanks for your interest! Estimo is in its **foundation phase** — the research and plan are
done, the code is arriving sprint by sprint. Early contributions are most valuable on the
items marked in [docs/ROADMAP.md](docs/ROADMAP.md).

## Ground rules

Everything in [AGENTS.md](AGENTS.md) applies to human contributors too — it is the
canonical workflow document (branch topology, commit convention, Definition of Done,
language policy, data rules). The short version:

- **Trunk-based:** branch from `main` (`feat/<scope>-<slug>`), squash-merge back, keep PRs
  scoped to one roadmap item.
- **Conventional Commits** in English.
- **No real customer data anywhere** — synthetic/sanitized fixtures only
  (see [SECURITY.md](SECURITY.md)). This is the one rule with zero tolerance.
- **Tests + evals:** code changes need tests; estimation-behavior changes need golden-set
  eval results in the PR description.
- **Docs discipline:** update `docs/ROADMAP.md` checkboxes and `CHANGELOG.md`
  (`[Unreleased]`) in the same PR; never add new planning documents.

## Discussing before building

Open an issue (English or Turkish both welcome) before large changes. Architectural
proposals should reference or add an ADR (`docs/adr/`). The product's non-negotiable
behaviors are in [docs/PRINCIPLES.md](docs/PRINCIPLES.md) — proposals that conflict with
them need to change the principle first (with evidence), not sneak past it.

## Licensing of contributions

Estimo is [Apache-2.0](LICENSE). By submitting a contribution you agree it is provided
under Apache-2.0 (inbound = outbound), per Section 5 of the license. Do not contribute
code you don't have the right to submit — and never code copied from `ee/`/`enterprise/`
directories of open-core projects.

## Setup

Tooling arrives with Sprint S1 (see roadmap). Until then, the repo is documentation-only
and the only "build" is reading [docs/RESEARCH.md](docs/RESEARCH.md).
