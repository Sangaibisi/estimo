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

## Identity layer (added 2026-08-03)

The delivered screens were deliberately spare; the identity pass layered a corporate
face on top **without touching the data-graphic rules** (marks stay flat; status and
evidence colors keep their reserved meanings):

- **Logo mark** — three range bars (optimistic / likely / pessimistic, the middle one
  full-opacity) on a **fixed** deep-navy gradient tile (`#2b5fa8 → #16355e`),
  rounded-square. It is the product's signature RangeBar as a monogram. Fixed, not
  theme tokens: the favicon cannot adapt, and a dark-theme lightened tile would wash
  the white bars out. Canonical files: `apps/web/app/icon.svg` (favicon) and
  `LogoMark` in `apps/web/components/icons.tsx` — keep the two in sync.
- **Brand gradient** — `--grad-brand` (`--brand-a` = accent → `--brand-b`; both
  themes define their own pair), deliberately **monochrome navy**: a second hue
  would crowd the reserved evidence colors (an earlier teal endpoint sat within a
  few RGB points of `--ev-wiki` and was replaced). **Chrome only**: the top-bar
  strip, the active rail edge, background washes. Never inside charts, bars, or
  status UI.
- **Icon set** — drawn inline SVGs on a 16px grid, 1.5px round-cap strokes,
  `currentColor` (`components/icons.tsx`). This supersedes the original
  "CSS-primitive squares" rail treatment; the underlying rule it enforced — no glyph
  font, no emoji — still stands.
- **Page headings** — each section heading carries its rail icon (`.page-h`), tying
  navigation and page identity together.
- **Washes** — a ~3% accent tint at the top of the body and on drop targets; subtle
  enough to survive both themes.

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
  [ADR-0001](../adr/0001-litellm-gateway-only.md). Status: the stage→profile table
  shipped 2026-08-03 (Admin → Model gateway, fed by `GET /v1/system`); the token/cost
  meters remain open — they need per-stage usage accounting the API does not yet keep.
