# Design System — Delivered Artifacts

Canonical design reference for the product UI. Where these artifacts and
[UI-VISION.md](../UI-VISION.md) disagree, **the delivered design wins**; discrepancies
are folded back into UI-VISION via PR.

## Current design language (2026-08 redesign)

[repository-map.dc.html](repository-map.dc.html) is the **source of truth** for the
product's visual language since the 2026-08 redesign: a single dark workstation theme
in OKLCH (violet-tinted near-black neutrals on hue 295, violet accent
`oklch(0.72 0.16 300)` with glows, data-flow cyan `oklch(0.74 0.13 200)`), JetBrains
Mono for labels/numbers/controls with tracked-out uppercase micro-labels, the system
Helvetica stack for prose, grid-paper canvases, and a restrained motion vocabulary
(`om-pulse`, edge-flow dashes, slow ambient orbs — all disabled under
`prefers-reduced-motion`). The UI is **English-only**; Turkish remains a data language
(ADR-0004). There is **no light theme** and no theme toggle.

The screen it draws — the Repository Map (typed repo nodes laid out by architectural
layer, directed API-call / data-flow relations, per-node inspector) — shipped as
`apps/web/app/map/page.tsx` and is the product's centerpiece surface.

## Files

| File | What it is |
|---|---|
| [repository-map.dc.html](repository-map.dc.html) | **Current design language** + the Repository Map screen (nodes, relations, layer columns, inspector, link modes). Dark OKLCH system. |
| [estimo-ui.dc.html](estimo-ui.dc.html) | First-generation system (2026-08-03, IBM Plex, light+dark). **Superseded as visual language**; still the canonical *screen inventory* — the 10 product screens' layout, states and microcopy ("Voice & anti-patterns"). |
| [estimo-wireframes.dc.html](estimo-wireframes.dc.html) | Lo-fi wireframe/flow companion to the first-generation system. |
| [support.js](support.js) | Viewer support script shipped with the exports. Not product code. |

Open the `.dc.html` files directly in a browser.

## Token summary (source of truth is the HTML; code home is `apps/web/app/tokens.css`)

- **Typefaces:** JetBrains Mono (labels, numbers, controls — self-hosted via
  `next/font`), Helvetica system stack (prose), IBM Plex Serif (BoE document view
  only — Turkish casing correctness + docx parity).
- **One dark theme:** OKLCH surfaces on hue 295 (`--bg`, `--surf*`, `--ink*`,
  `--mut`, `--line*`); no light palette, no `data-theme` switch.
- **Accent pair:** violet `--acc` (with `-bg`/`-line`/`-ink` companions and glow
  shadows) + data-flow cyan `--flow`. Edges: solid violet = API call, dashed cyan =
  data flow.
- **Evidence-type colors** (distinct from status colors, as UI-VISION §6 requires):
  `--ev-code`, `--ev-wiki`, `--ev-analog`, `--ev-ans` — restepped in OKLCH.
- **Semantic status:** `--ok` / `--warn` / `--crit` with `-bg` companions; shape
  still carries state alongside color (circle/diamond/square).
- **Geometry:** radius `--r: 8px` / `--r2: 11px`, dense row heights (`--rh`), deep
  shadows with an inset top highlight on raised cards.
- **Motion:** `om-pulse` (live indicators), `om-flow` (hot dashed edges stream),
  `om-drift-*` (ambient backdrop orbs); everything under the `.om-anim` class dies
  with `prefers-reduced-motion: reduce`.

## Identity layer

- **Logo mark** — three range bars (optimistic / likely / pessimistic, the middle one
  full-opacity) on a **fixed** violet gradient tile (`#a06ee8 → #5b2ea6`, the brand
  pair), rounded-square. It is the product's signature RangeBar as a monogram. Fixed,
  not theme tokens: the favicon cannot adapt. Canonical files: `apps/web/app/icon.svg`
  (favicon) and `LogoMark` in `apps/web/components/icons.tsx` — keep the two in sync.
- **Brand gradient** — `--grad-brand` (violet pair). **Chrome only**: brand tile,
  background washes. Never inside charts, bars, or status UI.
- **Icon set** — drawn inline SVGs on a 16px grid, 1.5px round-cap strokes,
  `currentColor` (`components/icons.tsx`); no glyph font, no emoji. The connector
  marks (per-provider tinted badges) are the one deliberate `currentColor` exception —
  a provider's identity color must not re-tint with rail state.
- **Page headings** — each section heading carries its rail icon (`.page-h`) with a
  soft accent glow.

## Consumption plan

- The example scenario used throughout the design — **Aurora Telecom, campaign-based
  installment plans** — is intentionally the same fictional universe as our fixtures
  (see [fixtures/README.md](../../fixtures/README.md)), so design examples, fixture BRDs
  and golden-set evals all tell one coherent story. The Repository Map's sample set
  (`web-portal-ui`, `integration-gateway`, …) is equally synthetic.
- The Admin screen's model-profile table (stage → named profile) is the UI contract
  for the gateway routing profiles defined in
  [ADR-0001](../adr/0001-litellm-gateway-only.md). The token/cost meters remain open —
  they need per-stage usage accounting the API does not yet keep.
- Repository Map persistence (projects, hand-drawn repos, relations) is client-side
  for now — the server-side model and its feed into the impact worker are the S14
  backend decisions (see [ROADMAP](../ROADMAP.md)).
