# Design System — Delivered Artifacts

Output of the design-system pass (Claude Design), delivered 2026-08-03 as
"Aurora Telecom Installment Wireframes.zip" and committed here as the canonical design
reference. Where these artifacts and [UI-VISION.md](../UI-VISION.md) disagree, **the
delivered design wins**; discrepancies are folded back into UI-VISION via PR.

## Files

| File | What it is |
|---|---|
| [estimo-ui.dc.html](estimo-ui.dc.html) | Hi-fi screens: Foundations + the 10 product screens (Workspace, Reading Room, Question Board, Impact Map, Estimate Desk, BoE Preview & Signature, Ledger & Analog Search, Calibration Dashboard, Knowledge Curation, Admin) + "Voice & anti-patterns" microcopy set. Light and dark themes. |
| [estimo-wireframes.dc.html](estimo-wireframes.dc.html) | Lo-fi wireframe/flow companion. |
| [support.js](support.js) | Viewer support script shipped with the export. Not product code. |

Open the `.dc.html` files directly in a browser.

## Token summary (source of truth is the HTML)

- **Typefaces:** IBM Plex Sans (UI), IBM Plex Mono (numbers/code).
- **Dual themes:** full light + dark palettes (`--bg`, `--surf`, `--ink`, `--mut`, `--line`).
- **Evidence-type colors** (distinct from status colors, as UI-VISION §6 requires):
  `--ev-code`, `--ev-wiki`, `--ev-analog`, `--ev-ans`.
- **Semantic status:** `--ok`, `--crit`, plus accent `--acc` (with `-bg`/`-line` companions).
- **Geometry:** radius `--r: 6px`, dense/comfortable row heights (`--rh`), shadow tokens.

## Consumption plan

- **S7-1** (see [ROADMAP](../ROADMAP.md)) converts these into code: design tokens →
  CSS custom properties/theme file, then the component library (RangeBar, EvidenceChip,
  AnchorWarning, DeltaIndicator, …) matching the hi-fi screens.
- The example scenario used throughout the design — **Aurora Telecom, campaign-based
  installment plans** — is intentionally the same fictional universe as our fixtures
  (see [fixtures/README.md](../../fixtures/README.md)), so design examples, fixture BRDs
  and golden-set evals all tell one coherent story.
- The Admin screen's model-profile table (stage → named profile, token/cost meters) is
  the UI contract for the gateway routing profiles defined in
  [ADR-0001](../adr/0001-litellm-gateway-only.md).
