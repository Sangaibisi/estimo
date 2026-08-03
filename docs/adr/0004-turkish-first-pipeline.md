# ADR-0004: English-first product, Turkish-first input

- **Status:** accepted (revised 2026-08-03, same day — originally "Turkish-first pipeline")
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

Estimo targets a global audience: the repository, documentation, UI and outputs default
to English. However, founding discovery fixed one hard fact: the **first target market is
Turkey**, and incoming customer BRDs are **Turkish** — a morphologically rich, agglutinative
language that degrades naive BM25 tokenization and biases English-centric embedding
models. Wiki content and code comments at first deployments are mixed Turkish/English.
Customer-facing BoE documents for Turkish operators must read as professional Turkish
with TR locale formatting (1.234,56).

## Decision

- **Product and repo are English-first:** all documentation, code, UI default locale
  (`en`) and default output templates are English.
- **Turkish input is a first-class pipeline requirement, not an afterthought:** structural
  parsing, the ambiguity gate, clarification-question generation and retrieval must be
  validated on Turkish content. Retrieval components (BM25 analyzer with Turkish
  stemming/lemmatization, multilingual embedder, reranker) are chosen by a **Turkish
  golden retrieval benchmark** built in S3 — never by English leaderboard rank alone.
- **Localization, not translation-as-patch:** `tr` is the first localization for UI and
  BoE output templates (professional Turkish, TR number/date formats). Further locales are
  additive.
- **Prompts are English** (instruction-following stability) but always carry source
  content untranslated; generated customer-facing text follows the estimate's locale.
- **Fixtures are Turkish** where they simulate customer input — synthetic Turkish BRDs
  are test data, consistent with the English-docs policy.

**Retrieval decision (2026-08-03, S3):** the lexical leg is locked as PostgreSQL's
built-in `turkish` snowball FTS (`to_tsvector`/`ts_rank_cd`, verified against the
pgvector image) with **query-side Turkish suffix-stripping + prefix matching**
(`taksit:*`) — measured on the golden retrieval set, raw snowball misses
derivational/possessive query forms (`taksitli`, `kampanyası`), and prefix-OR queries
restore recall while RRF fusion keeps precision. Dense-leg embedder and reranker
selection remains benchmark-pending: the harness and Turkish golden set live in
`evals/golden/retrieval-tr/`; the shoot-out runs at the first deployment with live
embedding endpoints (mock vectors cannot rank semantics).

## Consequences

- The S3 spike must produce the Turkish benchmark before locking the embedder/reranker.
- Fixture authoring requires genuinely Turkish, realistic telco BRD language.
- Entering additional markets is a localization task, not a re-architecture.
- Revisit triggers: benchmark shows prompt-language interference (then test Turkish
  prompts), or a Turkish-specialized embedder materially beats multilingual options, or
  the first non-Turkish deployment changes locale priorities.
