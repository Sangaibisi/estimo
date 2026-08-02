# Architecture Reference

Condensed from the founding research ([RESEARCH.md](RESEARCH.md) §5, Turkish, fully
sourced). This file is the canonical technical map; decisions live in [adr/](adr/).
The sprint-by-sprint build order is in [ROADMAP.md](ROADMAP.md).

## System overview

```mermaid
flowchart TB
    subgraph SRC["SOURCES"]
        BRD["BRD .docx (Turkish)"]
        CONF["Confluence wiki"]
        GIT["Git repositories"]
        ARCH["Past BRD + estimate archive (seed set)"]
    end

    subgraph KNW["KNOWLEDGE LAYER - four shelves"]
        PARSE["Structural parse: requirement table with stable IDs"]
        CODE["Code shelf: SCIP graph + repo map + module wiki"]
        WIKI["Wiki shelf: hybrid search + reranker + canonical pages"]
        LEDGER["Estimate ledger: item-estimate-actual triples"]
        ONTO["Ontology: module taxonomy, telco eTOM/SID optional"]
    end

    subgraph PIPE["PIPELINE - durable graph"]
        DEC["Decompose"]
        AMB["Ambiguity gate + clarification questions"]
        HITL["Human checkpoint: answers"]
        WRK["Per-item workers: code graph + search + analogs"]
        IMP["Impact map"]
        EST["Three-point ranges + assumptions + risks"]
        CRIT["Critic / consistency pass"]
        DOC["BoE document assembly"]
    end

    subgraph REV["REVIEW + CALIBRATION LOOP"]
        UI["Review UI: independent-first flow"]
        SIGN["Line-by-line sign-off"]
        ACT["Actuals feedback"]
        CAL["Calibration: range widths + analog selection"]
    end

    GW["OpenAI-compatible gateway (LiteLLM)"]

    BRD --> PARSE --> DEC
    CONF --> WIKI
    GIT --> CODE
    ARCH --> LEDGER
    ONTO --> DEC
    DEC --> AMB --> HITL --> WRK
    CODE --> WRK
    WIKI --> WRK
    LEDGER --> WRK
    WRK --> IMP --> EST --> CRIT --> DOC --> UI --> SIGN --> ACT --> CAL --> LEDGER
    PIPE -.all model calls.-> GW
```

## Components & chosen stack

Composition policy: established OSS is adopted behind internal interfaces; from-scratch
code is reserved for the differentiation core — see
[ADR-0005](adr/0005-oss-first-composition.md).

| Component | Choice | Status | Rationale / ADR |
|---|---|---|---|
| BRD parsing | Docling (primary), python-docx (surgical + BoE output), MarkItDown (fallback) | accepted | Structural tables/headings from enterprise .docx; all MIT ([RESEARCH §5.6]) |
| Pipeline orchestration | LangGraph (durable graph, checkpoints, HITL interrupts) + Pydantic AI (typed nodes) | accepted | Battle-tested, MIT, model-agnostic |
| Model access | OpenAI-compatible client → deployment's LiteLLM gateway; **no provider SDKs** | accepted | [ADR-0001](adr/0001-litellm-gateway-only.md) |
| API service | FastAPI (Python 3.12+) | proposed | Ecosystem fit with parse/pipeline packages |
| Storage | Postgres (+pgvector) for ledger, runs, chunks | proposed | One database until scale demands more |
| Wiki retrieval | Hybrid BM25 + dense (multilingual embedder) + reranker + contextual chunk headers | accepted | ~67% retrieval-failure reduction pattern; TR-first ([ADR-0004](adr/0004-turkish-first-pipeline.md)) |
| Code intelligence | tree-sitter repo map (MVP) → SCIP symbol graph (deterministic impact) → generated module wikis (deepwiki-open fork) | accepted | Cheap first, precise later; AGPL-free path |
| GraphRAG | **Skipped in v1** | accepted | Free graphs already exist (code graph, page hierarchy); revisit only for multi-hop needs |
| Knowledge curation | Canonical pages tier outranks raw wiki; freshness + authority scores on chunks | accepted | Stale-wiki poisoning defense |
| Calibration | Analog few-shot selection + conformal intervals + historical error distributions | accepted | The two evidence-backed accuracy levers (RESEARCH §3.2) |
| Evals | Golden synthetic set + Ragas/DeepEval/promptfoo offline; Langfuse online feedback | accepted | Naive-baseline reporting mandatory (PRINCIPLES #7) |
| Review UI | Next.js/TypeScript web app; `en` default locale, `tr` first localization | proposed | Design system incoming via [UI-VISION.md](UI-VISION.md); [ADR-0004](adr/0004-turkish-first-pipeline.md) |
| Connectors | First-party ingestors: Confluence v2 crawl (ACL+version metadata), Jira JQL cursor, git hosting via provider APIs + git protocol — **Bitbucket first-class** (Atlassian shops), GitHub, GitLab; webhook-triggered re-index | accepted | Bulk sync never via MCP (rate limits); [ADR-0002](adr/0002-atlassian-adjacent-core.md) |
| Atlassian surface | Thin Forge Rovo Agent front-door + product's own MCP server | planned | Distribution without platform lock-in ([ADR-0002](adr/0002-atlassian-adjacent-core.md)) |
| Deployment | **Fully containerized** — every component an OCI image on GHCR (multi-arch); `docker compose up` = dev & single-node deploys; Helm (same images) for k8s; ladder SaaS → VPC → BYOC → air-gap; stateless per tenant | accepted | Easy distribution; [ADR-0006](adr/0006-fully-containerized.md) |

## Indexing pipelines (ordered)

Three ingestion lanes feed the knowledge layer. Each is an **ordered, checkpointed,
resumable** pipeline — every stage idempotent, per-tenant namespaced, safe to re-run.

**Wiki lane** (Confluence → wiki shelf):
`crawl (v2 API, page+ACL+version, checkpointed)` → `normalize (HTML→markdown)` →
`structure-aware chunking (heading/table boundaries)` → `contextual header generation
(LLM, cached)` → `dual index write (BM25 + vector)` → `freshness/authority scoring`.
Incremental sync diffs page versions; a permission change re-syncs ACL metadata without
re-embedding. Canonical pages enter this lane post-approval with a rank boost.

**Code lane** (git hosting → code shelf):
`clone/fetch (Bitbucket/GitHub/GitLab APIs + git protocol)` → `tree-sitter repo map
(symbols, ranked)` → `SCIP index (defs/refs/dependents → graph store)` → `module-wiki
generation (nightly, LLM)` — generated module pages then flow through the wiki lane's
chunk/index stages. Webhook push events (or polling fallback) trigger incremental
re-index of changed paths only.

**Ledger lane** (seed import / live BoE writes → estimate ledger):
`ingest (import CLI or pipeline write)` → `validation vs schema
([LEDGER-SCHEMA.md](LEDGER-SCHEMA.md))` → `work-item embedding (title+description)` →
`error/review queues (unknown modules, rejected rows)`. Actuals arriving later update
calibration aggregates as a scheduled job.

**Query path** (at estimation time): `hybrid retrieve (BM25 + dense, ACL pre-filter,
freshness-weighted)` → `rerank` → `evidence assembly with URIs`. Retrieval never sees
content the requesting user couldn't read at the source.

## Non-negotiables encoded in code structure

- `packages/gateway/` is the **only** module importing an LLM client; CI greps for
  provider SDK imports elsewhere and fails the build.
- ACL metadata travels with every chunk from ingestion to retrieval; enforcement is a
  **pre-filter**, never prompt-level.
- Every pipeline stage emits evidence URIs; the BoE assembler refuses lines without them
  (PRINCIPLES #2 enforced mechanically).
- Judge model ≠ generator model in all eval and critic stages.
- Prompts are versioned files; changing one triggers the eval suite in CI.

## Known technical risks (tracked)

1. Static impact analysis holes on legacy Java (reflection, XML wiring, stored procedures)
   → hybrid SCIP + LLM judgment; low-confidence items get an explicit "discovery effort" line.
2. Turkish retrieval quality — embedder/reranker choices must be benchmarked on Turkish
   text (S3 spike, ADR-0004).
3. Confluence bulk sync is slow by platform design (no export API, points-based limits) —
   checkpointed incremental crawlers, days-long initial sync budgeted.
4. Ledger cold-start & data quality — seed-set import is a first-class product feature,
   not a script (S0/S3).
5. LLM-judge systematic bias — periodic human-labeled re-anchoring is scheduled work,
   not an afterthought.
