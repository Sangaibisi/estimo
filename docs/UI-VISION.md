# Estimo UI Vision

**Purpose of this file:** To serve as input to a design-system effort (Claude Design). It
describes what the product should *feel* like — its screens, component inventory, states,
and microcopy voice; color/typography/spacing decisions are left to the design system —
but every decision that needs making is listed here. The product's behavioral laws
([PRINCIPLES.md](PRINCIPLES.md)) are binding in the UI as well; above all: ranges, not
points; no line item without evidence; independent estimates first.

> ✅ **Design system delivered (2026-08-03):** see [design/](design/) — hi-fi screens for
> all 10 sections below, foundations (tokens, light+dark) and the voice set, in the
> Aurora Telecom installment scenario. Where this brief and the delivered design
> disagree, the design wins; fold discrepancies back here via PR.

---

## 1. Product personality

**Five adjectives:** Assured · Auditable · Engineer-serious (but not cold) · Data-dense
calm · Global-ready (localization-first).

**Anti-personality (never):** "Magic AI" sparkle, confetti, showing one big definitive
number, optimism that hides uncertainty, cutesy mascot voice, mixed-language interface
copy.

**Emotional target:** A solution architect looking at this screen should say "this tool
isn't deciding for me — it has prepared my work." Trust grows out of **traceability**,
not shine: next to every number sits its "why."

**Metaphor:** A law firm's case file + an engineering measurement instrument. An
"expert-witness dossier" aesthetic, not a "guess": register, evidence, signature.

## 2. Personas

| Persona | Role | What they expect from the UI |
|---|---|---|
| **Analyst (Effort Owner)** | Uploads the BRD, manages questions with the customer, drives the draft | Speed + a crisp missing-information list; one-click conversion of questions into customer format |
| **Dev Lead / Solution Architect (Reviewer)** | Technically validates line items, gives their own estimate, corrects | Evidence at a glance (code line, wiki page); an independent-first flow that moves fast |
| **Signing Authority (Delivery Manager)** | Approves the document, takes it to the customer | Complete assumption/risk registers; a trail of who approved what; clarity on the cone stage |
| **Admin** | Connections, model profiles, seed set import | Boring but transparent: sync statuses, error queues, cost meters |

## 3. Information architecture

```
Workspace
├── Estimates (list of BRD files — status-badged)
│   └── Estimate detail
│       ├── 1. Reading Room     (BRD ↔ requirements table)
│       ├── 2. Question Board   (clarification questions)
│       ├── 3. Impact Map       (module/service + evidence)
│       ├── 4. Estimate Desk    (main screen: line items + ranges)
│       ├── 5. BoE Preview      (document + signatures + export)
│       └── 6. Estimate History (versions, who changed what)
├── Ledger (past jobs, analog search, seed set import)
├── Calibration (dashboards: coverage, team curves, anchoring)
├── Knowledge (canonical-page curation, source freshness)
└── Admin (connections, models, roles)
```

Navigation: a left rail (icon+label, collapsible); inside an estimate, a **stage strip**
across the top (Reading → Questions → Impact → Estimate → BoE) — navigation that doubles
as pipeline status. Keyboard travel between stages (`[` `]`) and between line items
(`j/k`-style) — a power-user tool.

## 4. Screens

### 4.1 Workspace / Estimates list
- **Job:** The state of every estimate in flight, at a glance: stage, open question count,
  SLA age ("customer has been waiting 3 days for answers" — or the reverse, "draft has
  been waiting 4 hours for a signature").
- **Table-first**, not cards (data-dense culture): file name, customer (fictional), a mini
  stage strip, line-item count, total range (e.g. "34–52 pd"), owner of the pending action.
- New estimate: drag-and-drop a `.docx`; a "first read" progress state right at upload —
  the progress bar speaks *in stage names* ("Extracting tables… 12 requirements found").
- **Empty state:** on first use, a calm guide that explains the product in 90 seconds and
  points to the seed set import and a sample fixture BRD — no marketing language.

### 4.2 Reading Room
- **Job:** Verify the original BRD against its structured form, side by side.
- Left: a page-faithful BRD view (headings/tables highlightable). Right: the requirements
  table — every row with a stable identity like `REQ-014` and a two-way highlight link to
  its source paragraph.
- **Ambiguity heat:** a 3-level mark on the row edge (clear / partial / ambiguous). An
  ambiguous row goes to a question, not to a number — and *why* is explained inline, in
  one sentence.
- **Anchor quarantine indicator:** budget/date expressions found in the BRD carry a
  distinct style, with the tooltip "This information is hidden from the estimation engine
  (anchor protection)." This is the moment the product's backbone becomes visible in the
  UI — design it with care.

### 4.3 Question Board
- **Job:** Collect missing information from the customer, fast.
- Question cards: badged with the related `REQ`, reason stated ("no acceptance criteria"),
  status flow *Open → Sent → Answered → Applied to line item*.
- "Create customer set": compile selected questions into a single document/email text
  (formal register in the estimate's locale) — copy, or download as `.docx`.
- When an answer lands, affected line items show a "re-estimation suggested" pulse.

### 4.4 Impact Map
- **Job:** Make "where does this work touch the code" a discussion the team can actually
  have.
- A module/service-level graph or heat list (a view toggle between the two; the graph is
  for neighborhood intuition, not for show). Every node carries a confidence level
  (high/medium/low).
- Low confidence = a distinct style + a "discovery effort suggested" badge (uncertainty
  isn't hidden, it's priced).
- **Evidence panel:** clicking a node opens code references on the right (file+line, short
  preview), related wiki pages (title + freshness tag: "updated 8 months ago"), and
  analog jobs.

### 4.5 Estimate Desk (main screen — the heart of the design)
- **Job:** Turn the draft into a human decision, line item by line item.
- A dense table: item name, `REQ` links, impact summary, **range bar** (three-point
  visual: O—L—P; L emphasized but P never hidden), assumption/risk counters (toggleable
  row expansions), evidence chips, status (draft / reviewed / signed).
- **Independent-first mode (the critical flow):** when a reviewer first enters the desk,
  the AI columns come **closed** (not blurred — an honest "you first" panel): they enter
  their own range → "Reveal draft" → the AI range + the **delta indicator** (your range
  vs. the draft; do they intersect?). This flow must be low-friction: 5–10 seconds per
  line item.
- **Delphi mode:** multiple reviewers' ranges overlaid as anonymous horizontal lines; the
  width of disagreement is visible; identities only when the moderator reveals them.
- Totals strip (sticky bottom bar): the summed range across line items + the cone stage
  badge ("Concept stage: ±4x") + signature progress (12/18 items).
- Row editing: drag the range or type values; a mini "rationale" field at the moment of
  editing (optional but encouraged — a signal for calibration).

### 4.6 BoE Preview & Signature
- **Job:** The final form of the document that goes to the customer + corporate approval.
- Document preview (templated): scope, exclusions, line-item table, assumption register,
  risk register + contingency, cone stage, provenance appendices, signature page.
- Signature flow: role-based order (reviewer → signing authority); every signature is
  row-scoped (explicit about "what exactly you are approving"); any change after signing
  = a new version (diff view).
- Export: `.docx` (parameterized corporate template) + archival PDF.

### 4.7 Ledger & Analog Search
- Past jobs table: the job, its range as of that day, actuals, **deviation badge** (below /
  within / above the range), team/domain filters.
- Free-text search: "campaign-based installment plans" → analog cards (similarity
  percentage, a mini range-vs-actuals visual, click through to that day's BoE row).
- **Seed set import wizard:** xlsx/csv column mapping (a visual mapper), a queue of failed
  rows, and a "personal/customer-data checklist before anything enters" step.

### 4.8 Calibration Dashboard
- **Job:** The product's honesty showcase. The charts here are self-criticism, not
  marketing.
- Coverage chart: "Our P10–P90 range captured actuals 78% of the time (target 80%)" —
  always drawn with the nominal line; team/domain breakdowns.
- Naive-baseline comparison: pipeline vs. analog median; if there's no difference, it says
  there is no difference.
- Anchoring telemetry: the distribution gap between independent-first entries and
  post-reveal ones.
- Question impact: the rate of range revisions after clarification.

### 4.9 Knowledge Curation (canonical pages)
- Candidate-page queue (LLM distillation) → side-by-side source/candidate comparison →
  approve/revise → versioned publish. A freshness warning list ("this canonical page may
  have drifted from its source for 6 months").

### 4.10 Admin
- Connection cards (Confluence, Git, gateway): status, last sync, error queue, first-sync
  progress (with expectation management: "a large wiki can take days").
- Model profiles: stage→model mapping (named profiles only; no model-name bragging in the
  UI), cost meters.
- Roles & signing authorities.

## 5. Component inventory (expected from the design system)

The base library (table, form, dialog, toast, tabs, badge…) plus the Estimo-specific set:

1. **RangeBar** — the canonical visual of the three-point range; sizes: inline mini,
   table standard, comparison (two ranges stacked + intersection emphasis). A range, not
   a point.
2. **EvidenceChip** — a small chip with a type icon (code / wiki / analog / question
   answer); a hover/focus preview card (code-line snippet, wiki title + freshness, analog
   mini-range).
3. **AmbiguityMark** — 3 levels; color + shape together (never color alone).
4. **QuestionCard** — REQ link, reason line, status flow, an "add to set" action.
5. **AnalogCard** — similarity %, a mini visual of that day's range vs. actuals,
   deviation badge.
6. **DeltaIndicator** — independent estimate vs. draft range; intersection/disjoint
   states.
7. **ConeBadge** — cone-of-uncertainty stage (Concept ±4x → Approved ±1.25x); on every
   BoE header and in the totals strip.
8. **ConfidenceLevel** — high/medium/low; at low, a secondary "discovery effort" action.
9. **SignatureBlock** — who, when, which rows; version link.
10. **StageStrip** — pipeline status + navigation as one component.
11. **DeviationBadge** — actuals below / within / above the range.
12. **AnchorWarning** — the quarantined budget/date expression style + its explanatory
    tooltip.
13. **FreshnessTag** — source age ("updated 8 months ago"); a warning tone past the
    threshold.
14. **PipelineTimeline** — live stage progress during a run; loading states that speak
    in stage names.

## 6. Data-visualization language

- **Ranges everywhere, single numbers nowhere.** Where one number must appear (a totals
  heading, say), always with a "likely" emphasis + both ends of the range alongside.
- Coverage/calibration charts: the nominal target line is always drawn; success and
  failure get the same calm voice.
- Color semantics split in two: **status colors** (good/warning/critical — calibration,
  freshness, confidence) and **type colors** (evidence types, stages). They never mix;
  the accent color is a third role.
- Density: desktop-first, information-dense tables; numbers aligned with `tabular-nums`;
  row height in two modes, "dense" and "comfortable."

## 7. Tone & microcopy

The default locale is English; Turkish (`tr`) is the first localization (see
[ADR-0004](adr/0004-turkish-first-pipeline.md)). The rules below are language-agnostic —
every locale must carry the same voice.

- Formal but human; short sentences; avoid the passive voice ("We extracted 12
  requirements," not "Analysis completed").
- Honest uncertainty language: "Evidence is weak on this item — we added discovery effort
  to the range."
- Error copy: what happened + what to do ("We couldn't reach Confluence (401). Renew the
  connection key in Admin → Connections."). No apologies, no blame.
- Empty states teach: an empty Question Board gets one contextual sentence, like "Every
  requirement passed the gate — a good sign."
- Approval moments are dignified: no confetti at signing; "BoE v3 signed — ready to
  export."
- Number format (English default): `1,234.5 pd`; dates `Aug 12, 2026`; "person-days"
  abbreviates to `pd`, one form product-wide — consistent with the glossary.

## 8. Theme, accessibility, motion

- **Light and dark themes are equal citizens** (dark will be in demand for long reading
  sessions); token-driven, AA contrast in both.
- Color alone never carries state (mark + shape, always paired); the full flow works from
  the keyboard (above all, row-to-row travel and range editing on the Estimate Desk);
  focus states unmistakable.
- Motion is measured and meaningful: brief continuity on stage transitions, one carefully
  crafted transition at the draft's reveal (the independent-first moment); respect
  `prefers-reduced-motion`. No ornamental animation.

### Turkish localization notes (first market)

`tr` ships first, and these are requirements, not nice-to-haves:

- Typography: a typeface that handles the Turkish `İ/ı` casing distinction correctly.
- Long compound words need a table-cell strategy: smart truncation + tooltip rather than
  `hyphens`.
- Formats: numbers `1.234,5 a-g`, dates `12 Ağu 2026`; "adam-gün" abbreviates to `a-g`,
  applied as consistently as `pd` in English.

## 9. Deliverables expected from the design system

1. Token set: color roles (surface/neutral/accent + status + evidence-type palettes),
   type scale (two contexts: data-dense table + document reading), spacing/density in two
   modes, a radius/elevation language.
2. Specifications for the 14 bespoke components above (with their states:
   default/hover/focus/disabled/error; including empty/loading/error content states).
3. Three sample screen compositions: **Estimate Desk** (its two independent-first states,
   draft hidden and revealed), **Reading Room**, **Calibration Dashboard** — light + dark.
4. A voice-and-tone sample set: 10 pieces of microcopy (empty state, error, signature
   confirmation…) written in the design language.
5. An anti-example note: which "magic AI" patterns are consciously excluded.

---

*This vision comes to life in [ROADMAP.md](ROADMAP.md) S7; when the design-system
deliverables arrive, this file is updated, conflicting parts are corrected in the design
system's favor, and the decision is captured in an ADR.*
