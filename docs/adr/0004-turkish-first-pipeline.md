# ADR-0004: Turkish-first pipeline with multilingual retrieval

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

Founding discovery (2026-08-03): incoming BRDs are **Turkish**; wiki content and code
comments are mixed Turkish/English; the first user base works in Turkish. Turkish is
morphologically rich (agglutinative), which degrades naive BM25 tokenization and biases
English-centric embedding models; UI copy and the BoE output document must read as
professional Turkish, with numbers formatted per TR locale (1.234,56).

## Decision

Turkish is the pipeline's first-class language end to end: structural parsing, ambiguity
gate, clarification questions, estimate narratives and the BoE document are authored in
Turkish by default (i18n-ready, `tr` default / `en` planned). Retrieval uses multilingual
components chosen by a Turkish benchmark, not by English leaderboards: a Turkish-aware
analyzer for BM25 (stemming/lemmatization), a multilingual embedder and reranker validated
on a Turkish golden retrieval set built in S3. Prompts are authored in English (instruction-
following stability) but always carry Turkish content untranslated; outputs are Turkish.

## Consequences

- The S3 spike must produce a small Turkish retrieval benchmark before locking the
  embedder/reranker — leaderboard defaults are not trusted.
- Synthetic fixtures must be genuinely Turkish (realistic telco BRD language), which makes
  fixture authoring more work but keeps evals honest.
- English-market expansion later is a localization task, not a re-architecture.
- Revisit triggers: benchmark shows prompt-language interference (then test Turkish
  prompts), or a Turkish-specialized embedder materially beats multilingual options.
