# Design note: Functional-size (FP / COSMIC) optional layer (S10-7)

**Status:** design note — implementation deferred to the next cycle (explicitly a
roadmap non-goal for v1.x).

## Why an optional layer, not a core estimator

Estimo's accuracy lever is the **outside view** — analogy to the tenant's own
estimate↔actual history, calibrated with conformal intervals (RESEARCH §3.2, S6/S8).
Functional-size methods (IFPUG FPA, Nesma enhancement-FPA, COSMIC) are a **different**,
complementary paradigm: they size the *functionality* independently of history, which is
valuable for cold-start (no analogs) and for organizations that already price in function
points. They are a layer that produces an alternative size signal, never a replacement
for the analogy+calibration core.

## Where it plugs in

- **Input:** the S4 decomposition already yields work items with requirement text and
  module tags. A COSMIC pass classifies each item's data movements (Entry / Exit / Read /
  Write) to produce a CFP (COSMIC Function Point) count; a Nesma pass counts added /
  changed / deleted function points for enhancement work.
- **Output:** a second size estimate per line, shown **beside** the analogy band, with its
  own provenance chip — the estimator sees "analogy says X, functional size says Y" and
  the divergence is itself a signal. It never silently overrides the band.
- **Calibration:** once actuals accumulate, the CFP→person-day conversion is calibrated
  the same way analog transfer error is (S8) — the functional count is an input to
  calibration, not a fixed productivity constant (the classic FP failure mode).

## Why not now

- The core loop (BRD → decomposition → analogy bands → calibration → BoE) is the
  differentiation and is shipped and measured. A functional-size layer adds a large
  rules surface (counting standards, data-movement classification) whose value is
  bounded to cold-start and specific buyers.
- Doing it well needs the dogfood pilot's real BRDs to validate the counting heuristics
  against actuals — i.e. it should follow S8's pilot data, not precede it.

## Open questions for the next cycle

1. Automatic COSMIC data-movement extraction vs. a human-assisted counting UI.
2. Whether to expose CFP as a first-class ledger field (so historical function-point
   data can seed the conversion) or keep it a derived per-estimate annotation.
