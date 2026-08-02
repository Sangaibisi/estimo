# Evals — Golden Set Design (S0-6)

Estimo's estimation behavior is gated by evals ([AGENTS.md](../AGENTS.md) §6,
[PRINCIPLES](../docs/PRINCIPLES.md) #7). This document specifies the offline golden set
and metrics; the harness is built in S4-6.

## Layout (target)

```
evals/
├── golden/
│   ├── brd/                  # inputs: the fixture BRDs (referenced from fixtures/brd/)
│   ├── decomposition/        # reference work-item breakdowns per BRD (JSON)
│   ├── questions/            # reference clarification questions + rubric labels
│   ├── retrieval-tr/         # Turkish retrieval benchmark (S3-2): query → relevant docs
│   └── estimates/            # reference ranges per item + seed-ledger snapshot they assume
├── reports/                  # dated eval run outputs (committed: summary JSON/MD, not raw traces)
└── harness/                  # runners (S4-6): DeepEval/promptfoo configs + scoring code
```

Golden data lives in the Aurora universe ([fixtures/README.md](../fixtures/README.md));
references are authored by humans and versioned — changing a reference is a reviewed PR,
because it moves the bar.

## Metrics

| Stage | Metric | Definition |
|---|---|---|
| Parse (S2) | Segmentation accuracy | Extracted requirement units vs reference (match on planted `manifest.json`); anchor-detection recall must be 1.0 on planted anchors |
| Decomposition (S4) | Coverage / precision | Reference items found / spurious items introduced (fuzzy title+module matching) |
| Gate (S4) | Gate correctness | Planted-ambiguous items must fail the gate; clean items must pass (both directions scored) |
| Questions (S4) | Question quality | 1–5 rubric: addresses the real gap / answerable by customer / specific / non-duplicative; scored by judge panel (judge ≠ generator, order-randomized) + periodic human labels |
| Retrieval (S3) | Recall@k / nDCG | On the Turkish retrieval benchmark |
| Estimates (S6) | MAE / MdAE, Pred(25) | Against reference likely values |
| Estimates (S6) | Interval coverage | % of reference actuals inside stated ranges vs nominal (the calibration headline) |
| Estimates (S6) | **Δ vs naive baseline** | Naive = median of retrieved analogs' actuals. Reported in every run; a pipeline that doesn't beat naive is reported as exactly that. |

## Blinded evaluation protocol (F1 exit gate)

Three arms on the same golden BRDs, graders blind to arm:

1. **AI-only** — pipeline output untouched.
2. **Human-only** — estimator works from the BRD without Estimo.
3. **Hybrid** — independent-first flow: human estimate recorded, then AI draft revealed,
   human finalizes.

Compared on: decomposition coverage, question usefulness, estimate calibration vs
reference, and wall-clock time. Anchoring telemetry (|human-final − human-independent|
correlated with AI-draft values) is collected from arm 3. Hybrid must beat human-only on
time without losing calibration to pass the F1 gate ([ROADMAP](../docs/ROADMAP.md)).

## Rules

- References never contain real customer data — Aurora universe only.
- Eval runs pin prompt versions and model profiles; a changed prompt/profile is a new run.
- Judge prompts live here, versioned, with the same discipline as product prompts.
- Report format: one summary MD + JSON per run under `reports/`, dated, linked from the PR.
