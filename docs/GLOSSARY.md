# Glossary

Turkish equivalents are kept as a domain reference — BRDs and first-market artifacts
arrive in Turkish (see [ADR-0004](adr/0004-turkish-first-pipeline.md)); they are data
vocabulary, not documentation language.

| Term | Turkish equivalent | Meaning |
|---|---|---|
| **BRD** | İş Gereksinim Dokümanı | Customer-authored business requirements document (`.docx`, high-level, Turkish-first in our context). |
| **BoE** | Taslak Efor Dokümanı (Basis-of-Estimate) | The product's output artifact: scope basis, exclusions, decomposition, three-point ranges, assumption & risk registers, evidence provenance, signatures. |
| **Work item** | İş kalemi | One decomposed unit of the BRD that receives an estimate line. |
| **Ambiguity gate** | Belirsizlik kapısı | Pipeline stage that blocks unclear requirements and emits clarification questions instead of numbers. |
| **Clarification question** | Netleştirme sorusu | Question generated for the customer/analyst when a requirement is ambiguous or incomplete. |
| **Estimate ledger** | Efor defteri | The historical corpus: BRD → decomposition → given estimate → actual outcome triples; powers analogy retrieval and calibration. |
| **Seed set** | Tohum seti | Retrospective import of past BRDs + estimates that bootstraps the ledger before live usage. |
| **Analog / analogy card** | Analoji kartı | A similar past work item retrieved from the ledger, shown with its estimate, actual, and deviation. |
| **Canonical page** | Kanonik sayfa | Human-approved, versioned distilled domain brief that outranks raw wiki content at retrieval time. |
| **Independent-first** | Önce-bağımsız akışı | Review flow where the human records their own estimate before seeing the AI draft (anchoring protection). |
| **Anchoring telemetry** | Çıpalama telemetrisi | Logged delta between independent human estimates and post-reveal final numbers. |
| **Three-point range** | Üç-nokta aralık | Optimistic / likely / pessimistic effort band (PERT-style). |
| **Cone of uncertainty** | Belirsizlik konisi | Estimate variability as a function of project definition maturity; every BoE states its cone stage. |
| **Interval coverage** | Aralık kapsaması | Fraction of actuals that land inside stated ranges vs the nominal confidence — the primary calibration metric. |
| **Naive baseline** | Naif taban çizgisi | Median/mean of retrieved analogs; every eval reports the pipeline's delta against it. |
| **Impact map** | Etki haritası | Modules/services likely touched by a work item, derived from the code graph + LLM judgment, with confidence levels. |
| **Repo map** | Repo haritası | Token-budgeted structural summary of a codebase (tree-sitter symbols, ranked). |
| **Code graph** | Kod grafı | Symbol index — definitions, references, dependents — used for impact traversal. Populated today by tree-sitter; the store is indexer-agnostic so a SCIP index can replace it without changing the impact API. |
| **Gateway** | Geçit | The single OpenAI-compatible endpoint (LiteLLM in deployments) through which all model calls flow. |
| **Golden set** | Altın set | Frozen synthetic evaluation corpus with reference outputs used to regression-test estimation behavior. |
