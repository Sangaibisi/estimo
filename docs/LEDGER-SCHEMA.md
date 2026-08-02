# Estimate Ledger — Schema v0

The ledger is Estimo's rarest asset: the historical corpus of
**BRD → work item → given estimate → actual outcome** chains that powers analog
retrieval ([RESEARCH §3.2](RESEARCH.md)) and range calibration. This document is the
v0 specification (S0-4); the Postgres implementation lands in S3-1.

Discovery fact shaping this design: **actuals are not in Jira** at the founding
deployment — history arrives via retrospective **seed-set import** from the BRD +
estimate archive (spreadsheets/documents), so the schema is import-first and tolerant of
partial data.

## Entities

```
Brd 1─* WorkItem 1─1 EstimateLine 0..1─1 ActualOutcome
                 │
                 *─* EvidenceRef        (from live pipeline runs; empty for seed rows)
Brd 0..1─* ClarificationQuestion       (live runs only)
```

### Brd

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | uuid | ✓ | |
| `external_ref` | text | ✓ | Archive code or filename (e.g. `BRD-2024-017`) |
| `title` | text | ✓ | |
| `customer` | text | ✓ | Masked at import if sensitive (`OPERATOR-A`) |
| `language` | text | ✓ | `tr` expected initially |
| `received_at` | date | ○ | |
| `source_file_uri` | text | ○ | Internal archive pointer — **never the file itself** |
| `cone_stage` | enum | ○ | `concept / approved-scope / detailed` at estimation time |

### WorkItem

| Field | Type | Req | Notes |
|---|---|---|---|
| `id`, `brd_id` | uuid | ✓ | |
| `title` | text | ✓ | |
| `description` | text | ○ | |
| `module_tags` | text[] | ○ | From the module taxonomy (e.g. `billing-core`) |
| `domain_tags` | text[] | ○ | Business domain (billing, campaign, CRM, integration…) |
| `team` | text | ○ | Estimating/delivering team key |
| `embedding` | vector | — | Computed at import (title+description) for analog search |

### EstimateLine

| Field | Type | Req | Notes |
|---|---|---|---|
| `work_item_id` | uuid | ✓ | |
| `unit` | enum | ✓ | `person_day` (v0 single unit) |
| `optimistic / likely / pessimistic` | numeric | likely ✓, others ○ | Seed rows often carry a single number → stored as `likely`, flagged `point_only=true` |
| `assumptions` | text[] | ○ | |
| `estimated_at` | date | ○ | |
| `estimators` | text[] | ○ | Role keys, not necessarily names |
| `method` | enum | ○ | `expert / planning-poker / delphi / estimo-hybrid` |

### ActualOutcome

| Field | Type | Req | Notes |
|---|---|---|---|
| `work_item_id` | uuid | ✓ | |
| `actual_effort` | numeric | ✓ | person-days |
| `source` | enum | ✓ | `timesheet / project-report / expert-recall` — **recall is low-trust; weighted down in calibration** |
| `completed_at` | date | ○ | |
| `notes` | text | ○ | Scope-change flag: if scope changed materially, `scope_changed=true` → excluded from calibration by default |

Derived (computed, not stored by importers): `deviation = actual / likely`,
interval-hit flag, per-team/domain error distributions.

## Seed-set column mapping (import contract)

The import CLI (S3-1) accepts CSV/XLSX with a header-mapping step. Canonical column
names (aliases configurable at import):

| Canonical column | → Field | Req |
|---|---|---|
| `brd_ref`, `brd_title`, `customer`, `received_date` | Brd | `brd_ref`, `brd_title` ✓ |
| `item_title`, `item_desc`, `modules`, `domain`, `team` | WorkItem | `item_title` ✓ |
| `est_likely` (or `est_single`), `est_opt`, `est_pess`, `est_date`, `est_method` | EstimateLine | one of `est_likely`/`est_single` ✓ |
| `actual_effort`, `actual_source`, `completed_date`, `scope_changed` | ActualOutcome | ○ |

Import rules: rows without a mappable estimate are rejected to an error report (S3-1);
`modules` values outside the taxonomy go to a review queue rather than failing;
everything is per-tenant namespaced.

## Cold-start priors

Until the ledger has enough completed triples per team/domain (threshold decided in
evals), range widths fall back to external priors — TAWOS distributions and ISBSG
telecom-sector bands ([RESEARCH §4](RESEARCH.md)) — always labeled as prior-based in the
UI (ConeBadge + low ConfidenceLevel).
