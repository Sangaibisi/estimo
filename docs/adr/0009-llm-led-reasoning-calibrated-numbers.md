# ADR-0009 — LLM-led scope reasoning, calibration-led numbers

- **Status:** accepted
- **Date:** 2026-08-05
- **Deciders:** maintainer (direction), recorded after a four-lens architecture review
  against the working tree

## Context

The deployment target has sharpened: Estimo will sit at the **center of one company**,
standalone, fed by that company's Confluence and its (multiple) code repositories, and
its one job is **BRD in → effort out, in person-days, with a frontend/backend split**.
The maintainer raised two concerns and delegated the decision:

1. *"The LLM is used too little — the pipeline feels overly deterministic."*
2. *"Rovo / Atlassian channels are not bringing information in; I imagined our own LLM,
   fed by Rovo and the source, making the inference."*

The review found the first concern to be **more literally true than anyone claimed**:
the production API path makes **zero model calls**. `run_brd`, `resume_with_answers`
and `estimate_state` are all invoked without a gateway client and without a code graph
(`routers/estimates.py:214, :298, :529`), so the LLM ambiguity blend, LLM question
wording, LLM decomposition refinement, the within-band nudge — and even the **dense leg
of the estimator's own analog retrieval** — are dormant. The estimator sees worse
analogs than the ledger browse screen shows. Meanwhile the deterministic stand-ins that
do run are demo-shaped: module attribution is a 9-row keyword table of the fixture
scenario's modules, and code impact is a 14-entry hand-written Turkish→English synonym
dictionary — neither generalizes to a real company. The code graph the connectors build
on every sync is discarded after wiki generation and never reaches the estimate path.

The second concern contains a **direction-of-flow fact** that settles itself: Rovo is a
client-side surface. Rovo agents run *inside* Atlassian and can only call **out** (Forge
egress) — there is no mechanism by which Rovo pushes its index into an external system.
The sanctioned inflows are the REST APIs (which our connectors already use, with
version-pinned refs, ancestor-walk ACL resolution and checkpointed incremental crawl)
and the Teamwork Graph MCP (open beta, org-wide rate limits, cloud-only — already ruled
out as a hard dependency by ADR-0002 and RESEARCH.md).

Finally, the target output — a **discipline (FE/BE) split** — is representable nowhere:
no field on `WorkItem`, `EstimateLine`, `BoeDocument` or `ledger_entries` carries a
discipline.

## Decision

A three-layer division of labor. The pivot grows the LLM where the evidence supports it
and keeps it out of the one place it would destroy the product's claim.

### 1. Knowledge layer — REST connectors remain the ONLY writer to the evidence index

Nothing becomes evidence that did not pass through sync/pin ingestion. This is what
keeps evidence **version-pinned** (`wiki://page@version`, `repo://name@sha/path`),
**ACL-pre-filtered per caller**, and **anchor-quarantined before any model sees it**.

- Rejected: Estimo as an MCP client of Teamwork Graph *for retrieval at estimate time*.
  Three independent breaks: MCP results have no version identity a signed BoE can
  re-resolve; the MCP connection runs as one OAuth principal, laundering restricted
  pages past the per-caller ACL pre-filter; and live text entering prompts mid-loop
  bypasses the single `redact_anchors` choke point.
- Adopted (later, behind a flag): the **discovery-then-pin** hybrid. MCP/Rovo may
  *discover* candidate page IDs / issue keys — never text — which are then fetched via
  the existing REST single-page path, ACL-walked, version-pinned into the index, and
  only then eligible to become evidence. Precondition: a "pin this source now"
  primitive (the single-page fetch exists; only orchestration is missing).
- "Continuously fresh" is delivered by a per-connection **sync scheduler** (Confluence
  has no external webhook surface; git connections already have the HMAC webhook), with
  staleness *visibly surfaced*, not promised away.
- S10-4 (Forge Rovo Agent front-door) stays deferred and is reframed: it is
  **distribution** — "send to Estimo" from inside Jira/Confluence — not inflow. Client
  is the only direction Rovo can operate in.

### 2. Reasoning layer — this is where the LLM grows, a lot

- **Wire the gateway into the production estimate path first.** Passing the effective
  gateway client (and graph) into the three dead call sites activates everything that
  was already built. This is a deployment bug fixed before any architecture changes.
- **Agentic impact worker per work item** (replaces the synonym dictionary): a
  tool-using loop over (a) persisted per-repo CodeGraphs — persist what sync already
  builds instead of discarding it, (b) the knowledge index, (c) analog search.
  Output: a structured impact analysis — repos touched, modules, integration points,
  discovery risks, and a **discipline composition proposal** — with every claim bound
  to a resolvable `repo://` / `wiki://` / `ledger://` EvidenceRef. Multi-repo by
  construction: all synced repos' graphs and chunks are in scope.
- **Discipline dimension added to the schema**: composition on `WorkItem`,
  per-discipline sub-ranges on `EstimateLine`, per-discipline roll-up on the BoE
  ("X pd FE, Y pd BE"), and a discipline column on `ledger_entries` so actuals start
  accruing per slice. The LLM proposes the split with citations; the S12-7 slicing
  machinery calibrates it as data arrives. Until a slice clears `MIN_SAMPLES`, the
  split renders with an explicit "model-proposed, uncalibrated" badge — never as a
  grounded figure.

### 3. Number layer — calibration keeps the band; the LLM earns two named roles

- Where analogs exist: `likely` stays anchored on the **analog median × transfer
  quantiles**. Wrapping the tenant quantiles around an LLM-proposed likely is a trap:
  the quantiles are leave-one-out ratios measured against the analog median — applying
  them to a different anchor destroys the coverage guarantee (the codebase records a
  7%-coverage incident from exactly this class of mistake). The LLM's new roles here:
  **vetting analogs** (flagging non-comparable ones out of the median — an auditable,
  citable act; "which analogy you show matters more than which model you use") and the
  existing within-band nudge, now given the top-k analog cards as context.
- Where NO analogs exist: the arbitrary constant prior (1/3/8 pd) is replaced by an
  **evidence-grounded structured LLM proposal** — wrapped in a cone-stage-wide band,
  `Confidence.LOW`, `basis_note="model-proposed, uncalibrated"`, its errors tracked as
  a separate reference class until it earns its own quantiles. Strictly more
  informative than the constant, and violates no principle.
- Permanently out of the LLM's hands: the gate's blocking floor, frozen
  `issue_codes`, band edges where analogs exist, the independent-first gate, and
  anchor quarantine — anchoring bias is intra-company too, and redaction costs nothing.

### Identity consequence

The deployment is N=1, internal, center-of-company. The multi-tenant / BYOC / 
Marketplace surface is **frozen, not extended** — it stays correct and tested, but no
new investment until an external tenant exists.

### Measurement consequence

The anti-LLM evidence in RESEARCH.md §3.1 is 2023–24 vintage. Before the number policy
is tightened or loosened further, the eval harness gains a **free-form frontier-LLM
arm** (BRD + repo + wiki context, no band constraint) beside the calibrated arm and the
naive baseline — measured MAE/coverage decides how much rope the LLM gets, per
PRINCIPLES #7. Cited studies do not.

## Consequences

- The user-visible pivot lands in ROADMAP **S13** (S12-8/9 chrome work is deprioritized
  behind it): wire-the-gateway, persisted graphs + agentic impact worker, discipline
  dimension end to end, number-policy refinement, sync scheduler + pin primitive, the
  eval arm. The MCP discovery leg waits for Teamwork Graph GA or a measured recall gap.
- The FE/BE split ships **labeled uncalibrated first** and becomes calibrated as
  per-discipline actuals accrue — the same honest-silence pattern S12-7 established.
- Anyone adding a second write path into the evidence index (MCP text, Rovo push, a
  broad-read service account) is breaking this ADR, ADR-0002, and the ACL model at
  once; the review that catches it should cite this section.
