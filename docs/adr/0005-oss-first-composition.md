# ADR-0005: OSS-first composition — adopt proven components, build only the core

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

The founding research (RESEARCH.md §5.6) surveyed the open-source landscape and found
production-credible, license-safe (MIT/Apache-2.0) components for **every infrastructure
layer** of this system — document parsing (Docling), orchestration (LangGraph, Pydantic AI),
retrieval (LlamaIndex/Haystack, LightRAG), code intelligence (tree-sitter, SCIP), evals
(Langfuse, Ragas, DeepEval, promptfoo) — while finding **no OSS at all for the estimation
core itself**. Writing infrastructure from scratch would burn the differentiation budget on
solved problems, produce worse results than battle-tested projects, and slow the roadmap.
Conversely, careless adoption has real failure modes: license contamination (AGPL/SSPL/
BUSL/ELv2, open-core `ee/` directories), abandoned dependencies, framework lock-in, and
"platform for a screwdriver" bloat.

## Decision

For any technical capability, the default order is:

1. **ADOPT** an established OSS component when one passes the checklist below — always
   wrapped behind an internal interface in `packages/` so it stays swappable.
2. **FORK/EXTEND** when an OSS project is close but needs adaptation (e.g. deepwiki-open
   routed through the gateway) — tracked as a thin, rebaseable patch set.
3. **BUILD FROM SCRATCH** only for the differentiation core — decomposition quality,
   ambiguity gate, analog selection, calibration, the BoE workflow — or when no candidate
   passes the checklist.

**Adoption checklist (all required):**

- License is MIT/Apache-2.0/BSD (SPDX-verified); nothing pulled from `ee/`/`enterprise/`
  paths of open-core repos. Other licenses require their own ADR.
- **Credibility bar — at least one must hold:** the project is a de-facto industry
  standard for its niche (multiple independent production adopters, canonical in the
  ecosystem's own docs/comparisons); OR it is governed/backed by a major organization or
  foundation (e.g. Linux Foundation/LF AI & Data, Apache, Microsoft, IBM, Google-scale
  vendors); OR its adoption signals are overwhelming (GitHub stars in the tens of
  thousands with matching download/usage numbers). Clever-but-obscure repos never become
  dependencies regardless of technical merit — they are LEARN-FROM material at most.
  Stars alone are hype-prone; they satisfy the bar only together with real maintenance.
- Actively maintained (recent releases/commits, responsive issues) or trivially vendorable.
- Scope fits the need — we don't adopt a platform to use one function.
- Integration goes behind an internal interface; no OSS type leaks into `packages/core`
  domain models.
- Version pinned; upgrade path noted where the project is known to churn.

Contributions flow back upstream when fixes are general-purpose.

## Consequences

- Speed and quality: we stand on ecosystem-tested code and spend effort only where Lodestar
  is different; the stack stays aligned with industry-standard tooling contributors know.
- We accept wrapper-maintenance cost and third-party risk (mitigated by pinning, interface
  isolation, and the checklist's health gate).
- "Not built here" is the default; a from-scratch PR for infrastructure must justify
  itself against this ADR.
- Revisit triggers: a core dependency dies or relicenses; or interface isolation proves
  too leaky for a component (then vendor or replace).
