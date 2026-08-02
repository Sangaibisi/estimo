# Seed-Set Inventory Template (S0-5)

A checklist + inventory template for compiling the retrospective seed set **inside the
company**. Only this template lives in the repo; the filled inventory and the archive
files themselves must **never** be committed ([SECURITY.md](../SECURITY.md)). The output
of this process is a CSV/XLSX conforming to the
[ledger import contract](LEDGER-SCHEMA.md#seed-set-column-mapping-import-contract).

## Process

1. **Locate the archives.** Past BRDs (Word/PDF), estimate spreadsheets, proposal
   documents, project closure reports. Note where each lives (drive/wiki/mail) — pointers
   only.
2. **Inventory each BRD** using the table below (one row per BRD).
3. **Extract line items** for BRDs worth importing: work items + given estimates into the
   import CSV. A single-number estimate is fine (`est_single`); ranges are better.
4. **Hunt actuals.** Timesheets and project reports beat memory. Where only expert recall
   exists, record it but mark `actual_source=expert-recall` (calibration down-weights it).
   If scope changed materially between estimate and delivery, set `scope_changed=true`.
5. **Sanitize.** Mask customer names if required (`OPERATOR-A`); strip personal data from
   free-text; keep an internal-only key file mapping masks to real names if needed.
6. **Quality gate before import:** target from the roadmap exit gate — enough rows to be
   useful is roughly ≥ 30–50 work items with estimates, of which ≥ 15–20 have actuals;
   below that, Estimo still works but ranges lean on external priors (labeled as such).

## Inventory table (one row per BRD)

| Column | Values / notes |
|---|---|
| `brd_ref` | Archive code or filename |
| `year` | |
| `customer` | Real or masked |
| `domain` | billing / campaign / CRM / integration / … |
| `pages` | Rough size |
| `has_template` | yes / partial / no — informs parser expectations |
| `estimate_exists` | yes / no |
| `estimate_format` | spreadsheet / document table / mail / memory |
| `estimate_granularity` | per-item / per-phase / single-total |
| `actuals_exist` | yes / partial / no |
| `actuals_source` | timesheet / project-report / expert-recall |
| `scope_changed` | yes / no / unknown |
| `sensitivity` | public-safe / mask-customer / internal-only |
| `import_decision` | import / skip (reason) |

## What good looks like

The founding research is blunt: analogies from **your own** history are the single
strongest accuracy lever (+59% MAE in published work), and the ledger is the moat no
competitor can backfill. Every hour spent making this inventory complete and honest
compounds into estimate quality later — and dishonest actuals (recalled optimistically)
poison calibration, which is why source labeling above is mandatory.
