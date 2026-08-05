# Changelog

All notable changes to Estimo are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/) once code ships.
Until the first code release, entries track documentation and foundation milestones.

## [Unreleased]

### Added
- **S13-6 — the frontier eval arm.** `estimo-effort-eval --frontier` runs a
  free-form LLM band per held-out ledger row (no analogs, no band constraint,
  anchor-redacted like every model boundary) beside the calibrated arm and the
  naive baseline, measured on the same MAE/coverage axes with its own case count —
  it answers on rows the calibrated arm must skip for lack of analogs, which is
  much of its point. Opt-in by construction: the default harness stays offline and
  deterministic (CI unchanged), the gateway resolves panel-first like every CLI,
  and the report now emits the `evals/README.md`-promised JSON beside the Markdown
  plus a prompt-id line. It is these measured numbers — not model citations — that
  decide any future number-policy change (PRINCIPLES #7).
- **S13-5 — freshness: a per-connection sync scheduler and a "pin this source
  now" primitive.** Connections gain a panel-managed `sync_cadence_minutes`
  (migration 0019; NULL = the old manual/webhook-only behaviour — the column IS
  the off switch, no separate flag to drift from it). The scheduler is an
  in-process asyncio loop (ADR-0006 keeps the deployment at db/migrate/api/web):
  it enumerates cadenced connections cross-tenant the way the webhook path does,
  runs each sync pinned to its tenant, relies on the existing one-running-sync
  index against replica duplication, and counts a FAILED run as an attempt so a
  broken connection retries once per cadence, not once per tick. **Pinning**: a
  Confluence page ID or Jira issue key (validated as an injection boundary —
  digits only / PROJECT-123, nothing else reaches a REST path or JQL) is fetched
  through the connector's OWN single-item path — same ACL walk, same
  version-pinned ref — upserted synchronously so the caller learns in the
  response whether the source landed, and then **joins the re-sync set**: every
  successful sync of the connection re-fetches its pins, because the incremental
  crawl's watermark would otherwise skip an unmodified pinned page forever. Pin
  failures land on the pin row (`last_error`), never on the sync run. Admin tiles
  grow the cadence field and a pin box; unpinning stops the refresh but
  deliberately does not delete the ingested chunk — removing knowledge is a
  curation decision, not a side effect.
- **S13-4 — number policy: the analog median stays the anchor, the LLM's role
  around the number is bounded and auditable.** Three legs. (1) **Analog vetting**:
  before the band is computed the model may flag non-comparable analogs out of the
  median — every exclusion is printed in the assumption register naming the analog
  and the stated reason (auditable, reversible), verdicts for analogs that were
  never presented are discarded, and an unusable reply keeps the full set (refusing
  to vet is not evidence of incomparability). (2) The **within-band nudge** now sees
  the top-k analog cards (estimate prompt v2) — it judges the item against the
  delivered history, not a bare number. (3) The constant **1/3/8 pd no-analog prior
  is replaced**, when a model is available, by an evidence-grounded proposal fed the
  impact analysis's claims: validated, **widened to the cone-of-uncertainty floor**
  (a property of the output, not a hope about the model's self-restraint), LOW
  confidence, `basis_note="model-proposed, uncalibrated"`, a `note://model-proposal`
  reference and a 50%-of-likely contingency. The tenant's transfer quantiles are
  NEVER wrapped around a model-proposed likely — they are measured against the
  analog median (the 7%-coverage note), and the deterministic 1/3/8 prior remains
  the exact fallback for the no-model and any-failure paths.
- **S13-3 — the FE/BE discipline dimension, end to end.** The sharpened product goal
  is person-days *with a frontend/backend split*, so the split now exists at every
  layer instead of nowhere: `discipline` on `ledger_entries` (migration 0018, fed by
  the actuals form's new FE/BE select and a `discipline`/`disiplin`/`taraf` seed
  column — aliases fold at the boundary, anything unrecognized is rejected so a typo
  cannot mint a third slice), per-discipline sub-ranges on estimate lines, and
  "X pd FE, Y pd BE" totals on the BoE (web chip + docx section). The split's basis
  is explicit: the impact worker's cited composition first, the tenant's own
  historical FE/BE effort ratio per module second (the naive baseline — refusing to
  answer from one-sided history, because a ratio computed from backend rows alone
  would claim frontend work is free), and NOTHING when neither has a basis. Until a
  discipline's ledger slice clears MIN_SAMPLES the split renders with a
  "model-proposed, uncalibrated" badge — the S12-7 honest-silence pattern applied to
  a new dimension. Slicing rides the single shared predicate helper
  (`ledger_slice_conditions`), so the ledger browse, analog retrieval, the metrics
  headline and the per-slice calibration bars all agree on what "frontend" means;
  the calibration screen gains discipline bars and filter, the ledger a discipline
  facet. Per-discipline calibration data starts accruing NOW — which is the entire
  point of shipping the column before the split is trustworthy.
- **S13-2 — per-repo CodeGraphs persist, and scope reasoning became an agentic
  worker.** Sync built a CodeGraph on every git run, generated wiki pages from it,
  and threw it away — while the deployed estimate path never received a graph at
  all (`estimate_state` always ran `graph=None`, so `repo://` impact evidence and
  the synonym dictionary were dead in production). The graph now persists per
  connection (`code_graphs`, migration 0017, RLS'd, replaced in place on re-sync so
  it cannot churn per commit), rebuilt from stored files on load so the derived
  maps can never drift from the stored copy.

  On top of it: an **agentic impact worker** per work item — a tool-using LLM loop
  over every repo graph, the knowledge index (caller's ACL pre-filtered) and the
  analog ledger, speaking a JSON-action protocol over plain chat completions
  (deliberately not provider tool-calling: works against any OpenAI-compatible
  endpoint, zero gateway surgery). The model does the Turkish→identifier-English
  bridging the 14-entry synonym dictionary used to approximate; the dictionary
  survives only inside the deterministic fallback. **The model proposes, the
  verifier disposes**: every claim must cite evidence URIs, and a URI is kept only
  if a tool actually returned it this run or it independently resolves inside a
  loaded graph (right repo, right commit, real file, real lines) — fabricated
  citations delete the claim and are counted on the analysis. Analyses land on the
  BoE document (`impact`, versioned and frozen with the draft), module claims feed
  line evidence, discovery-risk claims feed the risk register with contingency, and
  the Impact Map's evidence panel gains the verified `repo://` code references
  S12-4 shipped without. Two unparseable turns, an unreachable gateway, or a
  missing client all degrade to the old deterministic graph heuristic — boxed as an
  analysis marked `deterministic`, never silently.
- **S13-1 (remainder) — every CLI now resolves the gateway the way the deployment does.**
  `estimo-embed` had grown a private copy of the panel-override read that silently
  diverged from the API's merge on three counts: it dropped panel-tuned timeouts and
  retries, resurrected deliberately-cleared profile rows (`or` where the API uses
  `.get` with a default), and swallowed an unsealable key without a log line. The
  merge now lives once, in `estimo_gateway.runtime` (`merge_gateway`,
  `deployment_gateway_config`, `deployment_gateway_client`); the API re-exports it,
  and `estimo-embed`, `estimo-boe` and `estimo-pipeline` all consult the panel
  override before falling back to `ESTIMO_GATEWAY__*` — so a panel-configured
  deployment's CLIs stop reporting "gateway is not configured" about a deployment
  whose Admin screen shows a working one. `estimo-pipeline` treats a missing
  `ESTIMO_DATABASE_URL` as the laptop case and stays env-only; the DB read is
  duck-typed over whatever engine the caller has, so the gateway package still has
  no database dependency.
- **S13-1 — the model gateway is panel-managed, and the estimate path finally uses it.**
  Two facts landed together. First, `Settings.gateway` became optional: the API boots
  with nothing in `.env`, and the endpoint, key, stage→model profiles and timeouts are
  set in **Admin → Model gateway** where the key is encrypted at rest. `.env.example`
  no longer configures a gateway at all — the vars survive commented out as an
  air-gapped escape hatch. `/v1/system` gained `configured`, `env_present` and a
  `source` of `unset`, the panel renders that state calmly instead of two red chips and
  a "every model call will fail" that describes a breakage that has not happened, and
  a half-filled `ESTIMO_GATEWAY__*` block no longer aborts startup — the worst possible
  failure for the one setting the panel exists to fix.

  Second, the production BRD→BoE path passes a gateway client. It never had: `run_brd`,
  `resume_with_answers` and `estimate_state` all ran with `client=None`, so the LLM
  ambiguity blend, question wording, decomposition refinement, the within-band nudge and
  the **dense leg of the estimator's own analog retrieval** were dormant while the
  ledger browse screen got hybrid search. The product was a deterministic keyword
  machine wearing an AI product's clothes (ADR-0009).

  **What the multi-role review then found — the live-run blockers.** The panel's second
  save DELETED the endpoint: the handler rebuilt the stored document from the request
  body, and the panel deliberately omits an unchanged base URL (the value it holds came
  back from `/v1/system` with userinfo stripped, so echoing it would persist a redacted
  URL over a working one). Saves are a patch over the stored row now. A panel-supplied
  URL was only validated as a side effect of constructing a full config — which is
  skipped when there is no credential yet — so a typo was persisted with HTTP 200 and
  surfaced later as a 500 from a different request, with the URL's embedded proxy
  password echoed into a 422 body; the endpoint is validated on its own, and the client
  is built outside the `try` that turns `ValueError` into an echoing 422. An empty
  `ESTIMO_GATEWAY__API_KEY` counted as configured. The unreachable latch fired on
  `APITimeoutError` too — one slow completion muted every remaining model-assisted step
  of the request — and logged the raw base URL, credentials and all. A gateway answering
  200 with an HTML interstitial or `{"choices": []}` raised `IndexError`/`AttributeError`
  out of the SDK, a type no caller catches, so a degradable step became a 500 that lost
  the upload. Per-request clients were never closed. And a draft built while the gateway
  was down came out with materially different bands and said nothing — it now carries a
  risk line saying the analog search ran on its lexical leg alone.

  **A near-miss worth recording, again.** A review agent rewrote `_pipeline_client` to
  read the environment instead of the effective config, marked it `# MUTANT`, and left
  it there; the working tree was restored but the mutation had already been baked into
  a built image. Every test stayed green, because they all run against settings that
  carry an env gateway — the mutant is invisible to them. There is now a test that
  configures the gateway ONLY through the panel, on an app whose environment is empty,
  and asserts the upload reaches it.

### Decided
- **ADR-0009 — LLM-led scope reasoning, calibration-led numbers.** The deployment target
  sharpened to a single company's center: BRD in → person-days out **with an FE/BE
  split, across multiple repos**. A four-lens architecture review against the working
  tree found the maintainer's "the LLM is used too little" concern to be *literally*
  true — the production estimate path makes **zero model calls** (`run_brd`,
  `resume_with_answers` and `estimate_state` all run without a gateway client, so even
  the estimator's dense retrieval leg is off), and the deterministic stand-ins are
  demo-shaped (a 9-row module keyword table, a 14-entry synonym dictionary). The
  decision: grow the LLM enormously in **reasoning** (agentic, citation-carrying impact
  analysis over persisted multi-repo code graphs + the knowledge index; discipline
  composition proposals), keep the **number** anchored on the ledger's calibration
  (with two new LLM roles: analog vetting, and an evidence-grounded proposal replacing
  the arbitrary 1/3/8 prior on the no-analog branch — labeled uncalibrated), and keep
  REST connectors as the **only writer** to the evidence index. Rovo cannot "feed"
  Estimo — it is a client-side surface that can only call out; the discovery-then-pin
  hybrid (MCP finds refs, REST pins them) is the flag-gated future path. Plan: ROADMAP
  **S13** (S12-8/9 chrome deprioritized behind it).

### Fixed
- **The first-run path pointed at a container that was not running.** `.env.example` is
  the file `docs/DEPLOY.md` tells an operator to copy, and it configured the gateway for
  the stub LLM — which only starts under `docker compose --profile mock`. The documented
  command therefore produced a deployment aimed at an unresolvable host; nothing failed
  at boot, and the first symptom was a connection error inside a feature, minutes later,
  on someone else's machine. The two lanes are now separate files: `.env.example` is the
  deployment template (placeholder endpoint, and the API logs a warning at every startup
  while it is still in place) and `.env.dev.example` is the demo lane that uses the stub.
  A repo guard fails CI if a compose service outside `db/migrate/api/web` ever loses its
  `profiles:` key, or if the deployment template starts naming the stub again.

### Added
- **S12-7 — the calibration screen grades itself, and says what it cannot measure.**
  The dashboard gained the design's slicing (team, domain, a 12/24-month window), a
  per-slice coverage bar per team and domain, percentage error beside absolute error,
  a question-impact panel, and an export. Three of those needed a decision about
  honesty before any of them could be drawn.

  **A rate needs a sample count, and below a floor it needs silence.** A per-slice bar
  computed from three closed jobs can only read 0% or 100%; neither says anything about
  the team. Slices below `MIN_SAMPLES` now come back with `coverage: null` and their
  count, and the screen states the reason. The same rule now applies to the rolling
  coverage line, which used to return a bare float that a caller could render alone.

  **"The difference is not meaningful" is a claim about a test.** The design's copy
  says it; the product now runs it — a two-sided sign test over the paired per-item
  errors, reported with its wins, losses and p-value, and worded plainly in whichever
  direction it falls. Percentage error ships alongside, with items under 2 pd excluded
  and counted, because a half-day miss on a one-day item is 50% and one such row
  dominates a mean.

  **Three live measurement defects fell out of the read.** Coverage counted every row
  with an `origin_ref`, which includes the Jira connector's `jira://` rows — those
  carry a single number, so each was an automatic miss charged to a pipeline that never
  estimated them. The denominator also counted rows with no band at all, turning "not a
  range" into "a range that failed". And the rolling window ordered by `created_at`,
  which a seed import writes identically for every row in the file, so "the last 20
  closed jobs" was an arbitrary 20 of 212; it now orders by when the work finished.

  **Two of the design's panels could not be built as drawn, and were not faked.** The
  anchoring strip "entered after the draft was revealed" describes something the
  product does not allow — bands are immutable and the reveal *is* the recording. What
  is real is a band recorded after a fully-signed draft became readable through the API
  or the `.docx`, and that is now stored (`independent_estimates.blind`, migration
  0015, NULLABLE because back-filling a claim about history nobody verified is how a
  measurement becomes a decoration). Likewise the per-reason bars: the gate has no
  detector for "undefined ownership" or "two readings possible", so the panel shows the
  codes the rules actually emit — now carried as `issue_codes` frozen on the question at
  ask time, because the LLM rewrites the human-facing reason and the gate re-scores the
  requirement once its answer lands, erasing the very issue the question was raised for.

  **What the review pass found (27 confirmed findings, 14 distinct defects).** The sign
  test computed its denominator as `2.0**decided`, which raises OverflowError at 1024
  decided pairs — not an exotic input but the success case, and it took the whole
  dashboard down with it, since every panel is built in one dict. It is summed in log
  space now. The p-value was also rounded to four decimals, so any strong result
  rendered as the impossible literal `p = 0`; anything under the floor now reads
  "< 0.0001". The window fix introduced its own regression: ordering by
  `completed_at DESC NULLS LAST` parked the window on whatever imported history carried
  dates, and since the product's own write path leaves that column NULL (the web client
  never sends it), recent work could never enter the drift signal — an undated row is
  now dated by when it was recorded. `blind` asked whether the CURRENT draft was signed,
  so a rebuild made a band typed by someone who had already read v1 look blind; it now
  asks whether ANY version was ever fully signed. The headline coverage had no sample
  floor, so picking a thin slice from the screen's own dropdown produced a one-row
  verdict on the product. `_question_reasons` deduplicated questions by bare id across
  estimates, and gate ids are derived from each BRD's own requirement codes — two BRDs
  that number requirements alike collapsed into one survivor. Slice rows carried no
  team/domain qualifier, so a team named after a domain rendered twice, identically.
  And the chart's tooltip paired the rolling coverage rate with the transfer
  distribution's sample count, printing "33% · n=33" for a three-row window (migration
  0016 stores the right count; older snapshots show none rather than a made-up one).

  **The one that matters most: the question-impact panel leaked what the desk gate
  withholds.** `GET /{id}/versions` refuses to disclose even the DIRECTION a line moved
  for a version that is not fully signed, because a line's three points scale with the
  same analog median. The new panel aggregated every frozen version with no such gate —
  and it is reachable by a reviewer, the exact role that gate exists for. It now diffs
  only fully-signed versions, and withholds its rates below a minimum contributing-
  estimate count, because an aggregate over one estimate is that estimate's own diff
  wearing a corpus-wide label. That is the fourth time this sprint series that a
  draft-derived signal reached a reader early through a surface nobody thought of as
  the desk.
- **S12-6 — the ledger gets its slices, an honest similarity, and a way in.** A seed
  set could only be imported from a shell (`estimo-ledger-import`), which meant the
  product's own memory could not be populated by the person who owns the data. There
  is now a four-step wizard on the Ledger screen: choose a CSV/XLSX, confirm the
  column mapping, confirm the privacy checklist, read the report. Three of those
  steps are load-bearing rather than decorative. The **mapping is the whole
  contract** — the importer applies no alias fallback underneath a confirmed
  mapping, so a column an operator deliberately unmapped cannot come back by name
  coincidence. The **checklist is enforced server-side**, because a checkbox that
  only exists in the browser is not an assertion that a file about to become
  permanent vendor memory carries no personal data (SECURITY.md). And the report
  separates rows that were *rejected* from rows that imported *without actuals* —
  the latter are kept (an estimate whose actual has not landed is still a true
  record) but counted apart, since calibration cannot use them.

  **The similarity percentage is measured, not ranked.** The design asks for an
  "81% match" chip. The fused RRF score that ordered the analogs is ordinal —
  1/(60+1) means "first", not "97% alike" — so rendering it as a percentage would
  have invented a figure on the one screen whose entire argument is that its numbers
  come from somewhere. Retrieval now carries the **cosine similarity** measured by
  the dense leg, and the chip appears only where one exists; where nothing was
  measured (no gateway, or entries with no embedding yet) the screen says so
  instead.

  **Team and domain slices go into the SQL of both retrieval legs**, not onto their
  output. Filtering the top-N after the fact would have shown three matches where
  the ledger holds forty — the reader would conclude their team had never done the
  work. The counts in the header describe the same slice. The table gains the
  design's `Delivered`, `Range that day`, `Team` and `BoE row` columns, the last
  linking a product-written entry back to the draft row it came from. An unreachable
  embedding endpoint now degrades ledger search to its lexical leg instead of
  failing the screen, and says which leg answered.

  **What the review pass found.** The clamp that was supposed to keep the similarity
  honest failed OPEN on the one non-finite input pgvector actually produces: a
  zero-vector embedding gives a NaN distance, `nan < 1.0` is False, so `min(1.0, nan)`
  returns 1.0 and the *least* comparable row in the ledger wore a "100% match" chip.
  Unmeasurable distances are now dropped rather than clamped. Re-importing a file
  appended a second copy of every row — one observation counted twice, in a table
  whose readers (calibration, analog retrieval) treat each row as an independent
  sample, so a duplicate both inflated the sample and became its own nearest analog;
  identical rows are now skipped and reported. A mapping posting two columns at one
  field was silently resolved by column order (and could differ row to row) and is
  now refused. Column samples were looked up by the stripped header while
  `csv.DictReader` keys rows by the header as written, so every whitespace-padded
  column previewed blank — and those are precisely the free-text columns the privacy
  checklist exists to check. The wizard also discarded the importer's parse warnings,
  presenting a row that *lost* its actual as a row that never had one; and its
  unknown-modules block could never fire, because the API passed no taxonomy — the
  deployment's own module history now stands in for one. Smaller: "N of M closed
  jobs" counted estimate-only rows as closed; a filter matching nothing said the
  ledger was empty; a failed or out-of-order load left the previous slice's rows
  under the new filters; facet lists were unbounded; and the lexical fallback caught
  only `GatewayError`, so a gateway answering 200 with an unparseable body turned
  search into a 500 from inside the provider SDK's own parser.

  **A near-miss worth recording.** One review agent proved the admin gate was
  untested by deleting `dependencies=[Depends(require_admin)]` from both import
  routes — and did not put it back, while `ruff --fix` silently removed the
  now-unused import. The whole suite stayed green, exactly as the finding predicted.
  The gate is restored and now pinned in `test_auth.py`, where auth is actually on;
  the ledger tests run in open mode, where every caller holds every role, so they
  could never have caught it. A request body is also bounded before routing now:
  Starlette parses multipart *before* dependencies resolve, spooling to disk with no
  ceiling, so an unauthenticated caller could make the server write to disk on the
  way to a 401.
- **S12-5 — the BoE keeps its versions, and two roles sign it.** `record.boe` was
  overwritten on every rebuild and `boe_version` was a bare counter, so the document
  a customer had been shown could not be reconstructed and the design's
  "Diff v2 → v3" had nothing to diff. Every build is now frozen into `boe_versions`
  (migration 0014, which also backfills the current draft of every existing
  estimate). Signing became the design's two-step flow: a reviewer signs the rows
  they reviewed — in one batch that is refused **whole** if any row is not eligible,
  because a partly-applied signature leaves the signer unsure what their name covers
  — and a signing authority then signs the scope once, allowed only after every line
  carries a reviewer's name. The authority's signature now reaches the exported
  `.docx`, which previously named every reviewer and not the person who authorised
  the document. The screen gains the contents rail, O/L/P columns with the likely
  emphasised, the **provenance appendix** (the `.docx` had carried it since S6; the
  screen had not, which is exactly the artifact/screen divergence the design
  forbids), and an in-document signature page naming its signers.

  **The diff is gated.** The first cut served every adjacent pair — including the one
  ending at the current *unsigned* draft — behind a docstring claiming band content
  was withheld, and the test asserted only that the words "optimistic"/"pessimistic"
  were absent: a false green that checked magnitudes while the direction signal
  walked out. A line's three points all scale with the same analog median, so
  "widened" on a **named** work item tells an estimator which way the draft moved
  before they record their own band — the inference the desk refuses to allow, which
  is why it withholds even the confidence grade. A diff is now served only between
  versions that were **both fully signed** (both documents were legitimately
  exportable), and the response says how many diffs are being withheld rather than
  letting an empty list read as "nothing changed". Also fixed: `sign-rows` deduped
  across *all* signers, so a second reviewer got a success response and their name
  never appeared; `line_signatures` gained the uniqueness constraint that was
  missing; and a raced rebuild answers 409 instead of 500.

- **S12-4 — the Impact Map is a map again.** The design's graph view ships: a
  dotted canvas with module cards laid out deterministically (a ring ordered by
  weight, so the same estimate always draws the same picture — a force simulation
  would look livelier and make the map change every visit, which is the opposite of
  what a map is for), SVG edges between modules, and a Graph/Heat toggle. **Edges
  are derived, not invented**: two modules are linked when a work item touches both,
  and an edge only ONE work item supports is drawn dashed, because a single
  co-occurrence is as likely incidental as structural.

  Selecting a module opens the docked evidence panel — what actually grounds the
  mapping: wiki pages (through the same ACL pre-filter every other retrieval path
  uses; a title is content) and analog jobs with their range and delivered actual.
  Per-module confidence is computed from **evidence coverage alone**, which is what
  makes it safe here: the estimator's own confidence grade is invertible against the
  draft (S12-1a), and the Impact Map runs before the desk, so nothing draft-derived
  may appear on it. Evidence is retrieved with the module name **plus the titles of
  the work items that touch it**, redacted — searching by tag alone matched almost
  nothing, because a ledger row reads "Taksitli fatura ekranı", not "billing-core",
  and an empty panel would have looked authoritative rather than uninformed. The
  titles go through `redact_anchors` first, like every other retrieval boundary: a
  work-item title inherits its requirement's first sentence verbatim, so unredacted
  the customer's stated budget would have decided which analogs a reader sees.

  **Coverage is withheld once a draft exists.** The first cut reasoned "this is
  coverage, not a band, so it is always safe" — and that was wrong: the estimator
  BRANCHES on the same analog lookup, taking a constant prior band with LOW
  confidence and a fixed contingency exactly when it comes back empty. So after the
  draft is built, "this module has zero analogs" *is* the closed band, on a screen
  that runs one step before the desk and has no independent-first gate — the very
  inversion S12-1a closed on the desk, reintroduced one stage earlier. Before a
  draft exists there is nothing to infer and the signal is served in full. Closing
  it for good needs a prior band that is not a constant (S12-1a), not a different
  threshold here. Work items the decomposer could not attribute now appear as an
  explicit `(unmapped)` bucket instead of vanishing, an analog whose scope changed
  says so rather than reading as a clean outcome, and code-wiki chunks are listed
  under Code references rather than under Wiki beside a line claiming no repository
  is connected.

- **S12-3 — the Question Board is the customer loop again.** `status` walked
  open → sent → answered → applied from the very first model, and nothing ever
  advanced it: dispatch was never recorded, so the board could only ever draw two
  lanes and "waiting 3 days" had nothing to count from. Sending a set now records
  **who it went to and when** (re-sending an already-sent question is refused rather
  than restarting its wait), an answer is recorded **per question and attributed**
  without rebuilding anything — recording and applying are separate because folding
  an answer in invalidates the draft and every band recorded against it — and
  applying marks the question applied and records **which work item it landed on**.
  A reader can add a question the gate missed. The customer letter is compiled
  **once, on the server**, and the preview, the clipboard and any future export read
  that one text: they used to disagree, so "Copy text" produced markdown bullets the
  customer never saw.

  Two invariants the board made reachable are now enforced. **The estimate row
  carries an optimistic lock** (migration 0013): `state` is one JSONB document that
  every workflow endpoint reads, mutates and writes back whole, so two overlapping
  requests both read the pre-image and the second erased the first — both callers
  getting 200, nothing logged. A review reproduced it in 11 of 12 *natural* races,
  and one user double-clicking was enough because the board's buttons did not
  disable during their own request. The loser now gets a 409 telling them to reload,
  and the buttons disable. **One live question per requirement**: the gate folds
  answers into requirement text through a map keyed by requirement, so a second
  question on one requirement meant only the last answer ever reached it while both
  cards claimed they were applied. And an unapplied manual question now blocks the
  draft — otherwise the New-question button changed nothing about whether a BoE
  could be built and signed over the very ambiguity a reader had just recorded
  (PRINCIPLES #3).

- **S12-2 — the Reading Room shows the document again.** The BRD body now survives
  the parse (`ParsedBrd.blocks`, capped at 120k characters with `body_truncated`
  saying so) and is served by a dedicated `GET /v1/estimates/{id}/source`, so the
  Reading Room can put the source beside its structured form the way the design
  draws it: the document in serif on the left, requirements with an ambiguity heat
  stripe on the right, and **selecting a row scrolls to and highlights the paragraph
  it came from** — the two panes address each other through `source_ref`, the same
  string the parser already stamped on both. Quarantined anchors are rendered in
  place inside the document, not only in the table. Gate findings read as sentences
  ("No acceptance criteria — there is no stated condition for calling this done.")
  instead of raw slugs; the slug stays the contract and an unknown one falls back to
  itself rather than vanishing. The body is fetched only when the Reading Room is
  open and stripped from `GET /v1/estimates/{id}` — and from `_summary`, which was
  otherwise validating a whole document per row on the estimates list.

  Two properties of the body are guarded by tests because the first cut got both
  wrong: the budget is counted in **serialized bytes** (charging block text alone
  under-counted by 3.6x on this repo's own fixture and by two orders of magnitude on
  a document of many short paragraphs, so a 12 KB `.docx` could have persisted an
  18 MB row), and **a block a requirement points at is never dropped** (extraction
  reads the whole document while the body was cut at a prefix, and a BRD keeps its
  requirements at the END — so truncation orphaned exactly the rows the screen
  exists for, and clicking one did nothing at all). A single oversized block is
  clipped rather than ending the document. The pane's scroll is computed against the
  container instead of `scrollIntoView`, after `behavior: "smooth"` was observed to
  move nothing while the highlight still appeared — the visible half of the feature
  made the broken half look fine.

- **S12-1 — the Estimate Desk matches its design.** The desk now carries the
  design's full column set in its order: REQ ids linking a line back to the BRD,
  the mapping **Confidence** grade, a `+ discovery N pd` chip wherever weak
  evidence bought contingency, the delta as a range-**relationship** chip (ranges
  intersect / disjoint — discuss) with the signed number secondary, per-row Status,
  and evidence aggregated per kind with counts instead of silently truncating after
  three. Confidence and the discovery chip appear **after** the reveal, not in the
  closed state the design draws them in: an audit found them invertible against our
  own estimator (the no-analog branch pins band, grade and contingency together),
  so showing them early would hand over the band and corrupt the anchoring
  measurement. The gate now covers every draft-derived field, pinned by a test that
  fails if any of them reaches a closed row (ROADMAP S12-1a). **Blocked
  requirements appear as held rows**: leaving them off made the desk look complete
  while a requirement sat unpriced behind an open question. An optional
  **rationale** is captured at entry (migration 0012) and shown in the expanded
  row — the only record of *why* a band was what it was; it is capturable only
  before the reveal, after which any rationale is a rationalization of the delta.
  The sticky footer adds the **ConeBadge** (concept ±4x / approved scope ±1.6x /
  detailed ±1.25x — PRINCIPLES #1), a signature progress bar, and switches from
  "your subtotal" to the estimate of record once every item is revealed.
- **Design parity, first pass (S12).** A 12-auditor sweep against the delivered
  design found 99 verified gaps; the highest-value small ones shipped: desk
  Confidence column and A/R column with an expandable assumptions/risks panel
  (the data was already in the payload, never rendered), anchor quarantine pills
  showing the withheld snippet (replacing an emoji count chip), the workspace's
  labeled stage strip with a corrected stage derivation (BoE-stage rows displayed
  one stage behind), ledger deviation graded against the RANGE (within/above/below,
  shaped chips) instead of a bare multiplier, an analog-match card grid whose
  actual-effort tick may sit outside the band, and the BoE's assumption register +
  risks & contingency sections on screen. The remaining gaps are recorded honestly
  as ROADMAP S12-1…S12-9 rather than left implied — including the design's
  pre-signature draft view, which stays closed on purpose: the API withholds the
  document until sign-off because it carries every line's band, and showing it
  would defeat the independent-first gate on the desk (S12-5).
- **Runtime configuration in the product (ADR-0008).** The Admin panel now EDITS the
  model gateway — base URL, API key, stage→profile routing, timeouts — via
  `PUT /v1/system/gateway`, stored in a new `runtime_settings` table and overriding
  the environment per field, effective immediately (env vars become bootstrap
  defaults). Connections accept the credential itself as an alternative to the
  env-var-name lane. Panel-entered secrets are SEALED before storage: encrypted when
  `ESTIMO_SECRET_KEY` is set, visibly `plain:`-prefixed with a UI warning when not —
  and never serialized back out of the API either way. OIDC and database URLs stay
  deliberately env-only (a bad auth save would lock admins out of the panel that
  could fix it). Migration 0011.
- **UI copy: Turkish terminology pass.** The invented loanword "estime" is gone —
  the TR locale now uses the plain "tahmin" family, plus clearer rail labels
  ("Kayıt Defteri", "Bilgi Bankası"). `<html lang>` follows the chosen locale so
  Turkish labels uppercase İ correctly. The density toggle (Dense/Comfortable) was
  removed as operator noise; the workstation layout is pinned dense.
- **Admin → Model gateway & runtime panels + `GET /v1/system`.** The design's Admin
  screen always promised a model-profile table; the **stage→profile half** of that
  contract now exists (the token/cost meters half still needs per-stage usage
  accounting and stays open), fed by a new admin-only endpoint that reports the
  *redacted* runtime configuration — gateway base URL (userinfo stripped), key
  **presence** (never the value), profiles, auth mode/claims, database
  host/name/role (never the DSN), CORS. A companion `POST /v1/system/gateway-check`
  does one timed round-trip through the configured gateway so an operator can verify
  LLM connectivity from the product instead of the container logs; failure reasons
  are sanitized to *our* words, because upstream gateways have been known to echo
  the API key they were shown back into error bodies. (This surface shipped
  read-only under ADR-0006 and became editable later the same day under ADR-0008 —
  see the runtime-configuration entry above.)
- **Visual identity layer.** A logo mark built from the product's own RangeBar
  (three O/L/P bars on the brand gradient), shipped as the favicon and the top-bar
  brand; a drawn SVG icon set (16px grid, stroke, `currentColor`) for the left rail
  and page headings; brand-gradient chrome accents (top strip, active-rail edge,
  background washes) in both themes. Data graphics are untouched — gradients live on
  chrome only, and status/evidence colors keep their reserved meanings
  (docs/design/README.md, "Identity layer").
- **A dense leg for the chunk shelf** (`dense_chunk_ids`, `hybrid_chunk_ids`). S11-8's
  first cut wrote `knowledge_chunks.embedding` for a column nothing read: only the
  *ledger* had a dense path, so every chunk embedded was cost without retrieval benefit,
  and "retrieval is hybrid" was true of analog lookup but not of the wiki or code
  shelves. Both dense legs carry the same ACL pre-filter as their lexical counterparts —
  vector similarity has no notion of permission, so a dense path without it is a full
  bypass reachable by anyone who can phrase a query.
- **S11-8 embedding writer — retrieval is hybrid in fact, not just in the diagram.**
  Nothing in this repository had ever written an embedding: the only `.embed()` call
  embedded the *query*, so `dense_ledger_ids` filtered `embedding IS NOT NULL` against
  zero rows and RRF fused a single ranking, in every deployment, for the whole life of
  the project. `embed_pending` fills chunk and ledger vectors through the gateway
  (profile `embedding`, inert when unconfigured), running after each connector sync and
  on demand via a new `estimo-embed` CLI. Batches commit independently so a rate limit
  mid-backfill keeps the completed half; an oversized page is capped and reported rather
  than failing the batch behind it (there is no chunker yet, so a "chunk" is a whole
  page); and the model id and dimension are stored per row, so switching embedders drops
  old rows OUT of the dense leg rather than scoring them in the wrong vector space.
  The embedding pass runs *after* a sync is marked succeeded and is reported separately:
  a gateway outage must not turn a completed multi-day crawl into a failed run.
  **Unmeasured on purpose** — whether the dense leg improves Turkish ranking still needs
  a live embedding endpoint (the S3-2 shoot-out). This ships the data path, not a
  quality claim.
- **Ledger attribution (part of S11-4; the sliced curves themselves are not built).**
  `record_actual` copied `team` and `domain_tags` off the `WorkItem`, and the pipeline
  never sets either — a BRD says what to build, not who builds it — so every ledger row
  the product wrote landed with `team = NULL`. Measured on a live instance: zero of
  zero product-origin rows carried a team. That is unrecoverable data, since nobody
  reconstructs delivery attribution a year later, which is why it ships now rather than
  with the curves it enables. `POST /actuals` takes optional `team`/`domain_tags` from
  whoever closes the loop, normalized with `tr_lower` at both write paths so `Billing`
  and `billing` cannot become two slices, and `GET /v1/metrics/overview` gained an
  `attribution` block so "attribution shipped" stays distinguishable from "attribution
  arrives" — the field is optional, so silence is a real outcome and worth counting.
- **S11-3 Delphi overlay**: the estimate desk shows every panelist's band for an item as
  anonymous lines over the consensus range, with the spread and an intersect/disjoint
  verdict. Two server-side gates, each proven load-bearing by removing it and watching
  the test go red: you must have recorded your own band for that item (the panel is
  otherwise a second route to other people's numbers, past the independent-first gate),
  and at least three estimators must have recorded on it. Below either gate the block
  carries no band-shaped number at all — with two panelists a median plus your own band
  reconstructs the other person's exactly, so a "summary only" concession would leak the
  same data with extra steps. Bands sort by value and re-sort per item, so no line maps
  to a person. Moderator identity reveal is not built and the design caption promising
  it was rewritten rather than shipped as a false promise.
- **S10 authN/Z** (`apps/api/auth.py`): provider-agnostic OIDC bearer-token validation
  (PyJWT + PyJWKClient — `python-jose` banned) against the customer's own IdP, with a
  role model (`estimator` < `reviewer` < `signing_authority` < `admin`). Opt-in: with
  no issuer configured the API runs open in single-tenant mode. Hardening: asymmetric
  algorithm allow-list (no alg-confusion), `iss`/`aud`/`exp`/`sub` required, last-known-
  good JWKS fallback. Sign-off requires a signing authority; connectors/admin require
  an admin (ADR-0007).
- **S10 multi-tenant isolation** (migration `0009`): PostgreSQL Row-Level Security on
  every tenant table, keyed on a transaction-local `app.current_tenant` GUC set per
  request from the token's tenant claim; a dedicated `NOSUPERUSER NOBYPASSRLS`
  `estimo_app` runtime role. Proven by a test that connects as that role and shows
  cross-tenant reads return nothing and cross-tenant writes are refused. A well-known
  DEFAULT_TENANT preserves single-tenant deployments with no data migration.
- **S10 MCP server** (`/mcp`, FastMCP 3.x over streamable HTTP): read tools
  `list_estimates`, `get_estimate_lines`, `get_decomposition`, sharing the API's tenant
  isolation and OIDC auth.
- **S10 packaging**: a Helm chart (`infra/helm/estimo`) for Kubernetes/BYOC (bundled or
  external Postgres, migration hook, runtime-injected web API origin), a deployment
  guide (`docs/DEPLOY.md`, incl. air-gapped notes), and design notes for the Atlassian
  Forge Rovo Agent front-door (S10-4) and the optional FP/COSMIC functional-size layer
  (S10-7).
- **S9 connectors** (`packages/connectors`, migration `0007`): live knowledge from
  real sources. Confluence Cloud crawler (v2 cursor pagination, v1-only read
  restrictions mapped onto retrieval ACL keys, checkpointed CQL incremental sync,
  points-budget pacing that honors `Retry-After` and slows on
  `X-RateLimit-NearLimit`); **Bitbucket-first** git hosting (access-token auth —
  app passwords were removed upstream 2026-07-28 — repo listing via the `next`
  URL, webhook secrets with `X-Hub-Signature` HMAC verification over raw bytes)
  plus GitHub/GitLab equivalents and a plain-git fallback; repo sync clones with
  the git binary (credentials via an ephemeral `GIT_ASKPASS`, never in URLs or
  argv) and feeds the S5 index → module wikis with connection ACL and commit-time
  freshness; optional Jira pull on the post-410 `/search/jql` endpoint with
  per-site story-points field discovery.
- **S9 curation + honesty**: canonical-pages flow (LLM drafts a candidate with
  recorded provenance; only HUMAN-approved pages enter retrieval, at top
  authority 0.95), authority as a relevance tie-breaker, `is_stale` (18-month)
  staleness surfaced in the curation UI, and a mandatory ACL pre-filter
  regression test (a restricted chunk is mechanically invisible to other keys).
  Admin → Connections UI: env-indirected secrets (names only), sync status,
  webhook endpoint per connection.
- **S8 calibration loop** (`packages/estimate/loop.py`, migration `0006`): recording an
  actual turns the signed line into a first-class ledger row
  (`origin_ref = estimate://…`), applies bounded outcome feedback to the `ledger://`
  analogs that backed the line (folded into `find_analogs` ranking as a ±2-position
  nudge — retrieval similarity stays primary), and snapshots the transfer-error
  quantiles + rolling coverage per event. Design web-verified: at this ledger scale,
  event-driven full recompute beats online/streaming conformal updates; drift
  surfaces via rolling coverage, never chased silently.
- **S8 actuals entry**: `POST/GET /v1/estimates/{id}/actuals` (attach to the fully
  signed estimate of record; scope-changed actuals are stored but excluded from
  feedback and calibration) + an Actuals tab in the web UI with per-line deviation.
- **S8 honesty dashboards**: `GET /v1/metrics/overview` + `/dashboard` page — interval
  coverage vs nominal over calibration snapshots, anchoring telemetry (mean |Δ| and
  near-zero-delta share), MAE vs the naive median baseline, and DORA-style
  second-order tiles (WIP, question-revision rate, rebuild share). Every rate ships
  with its sample count; small samples are labeled, never hidden.
- **S8 observability (opt-in)**: `docker compose --profile observability up` runs a
  pinned Langfuse v4 self-host stack (web/worker + dedicated Postgres, ClickHouse,
  Redis, MinIO — upstream sizes it at ~4 cores/16 GiB); the api forwards telemetry
  events and anchoring scores via the MIT `langfuse` SDK **only when `LANGFUSE_*`
  env is set** — unset means a complete no-op.
- **S7 review UI** (`apps/web` + `apps/api` workflow endpoints): Next.js estimation
  workspace — BRD upload, requirement/question board with quality-gated answers, the
  **independent-first Estimate Desk** (the server keeps the AI band locked until the
  estimator records their own three-point band; reveal shows the delta and evidence
  chips; per-line sign-off), and Turkish BoE `.docx` export. `en` default locale with
  `tr` as the first localization; design tokens from the S0 design-system output.
- **S7 web containerization**: multi-stage `apps/web/Dockerfile` (standalone Next
  output, non-root, healthcheck), compose `web` service, and CI publish of
  `ghcr.io/sangaibisi/estimo-web` (multi-arch, SBOM + provenance). The browser-visible
  API origin is injected at **runtime** from `ESTIMO_API_URL` — never baked into the
  image at build time.

- **S6 estimation** (`packages/estimate`): analog-grounded three-point bands with
  conformal-style calibration on the ledger's **analog-transfer** error (leave-one-out
  actual/analog-median quantiles — measured leave-one-out on the 15-row synthetic seed
  ledger: **87% interval coverage at nominal 80%**, and MAE 6.35 pd against a naive
  analog-median baseline of 7.07 pd. Calibrating on per-entry estimate deviation instead
  gave 7% coverage, which is why the transfer distribution is the one used. The
  quantiles are fit in-sample on 15 rows, so these numbers demonstrate the mechanism,
  not field accuracy — see `evals/reports/2026-08-03-s6-loo-eval.md`). Cold-start priors below 8 samples (always labeled), small-item overhead
  floors, expert-recall down-weighting. The estimator refuses non-ready states
  (PRINCIPLES #3), attaches ledger://+repo://+answer:// evidence to every line,
  converts LOW-confidence impacts into discovery risks with contingency, and lets the
  gateway nudge likely only WITHIN the band (anchors redacted, PRINCIPLES #5).
  Deterministic critic (gate-leak, duplicates, spread sanity, missing cold-start
  assumption), locale-aware BoE `.docx` renderer (full professional anatomy, TR
  number formatting), `estimo-boe` and `estimo-effort-eval` CLIs, LOO eval report in
  `evals/reports/2026-08-03-s6-loo-eval.md`.
- **S5 code shelf** (`packages/code`): tree-sitter symbol graph for Java/TypeScript
  (indexer-agnostic store — SCIP loader slots in at the first real build chain), ranked
  token-budgeted repo map, deterministic module wikis (purpose/interfaces/dependencies,
  optional gateway refinement) ingested into the knowledge shelf at authority 0.7, and
  the impact worker with a confidence ladder (symbol match HIGH → import neighborhood
  MEDIUM → keyword-only LOW with an explicit discovery-effort suggestion). Turkish→
  identifier synonym bridge (taksit→installment …); every impact claim carries a
  validated `repo://…#L–L` evidence URI. Synthetic meridyen-mini fixture repo with
  known change scenarios asserted in CI.
- **S4 pipeline** (`packages/pipeline`): LangGraph state machine parse → ambiguity gate →
  clarification questions → decomposition, with an offline deterministic floor at every
  node (a down or misbehaving gateway degrades quality, never correctness). The gate
  law is mechanical: blocked requirements own no work items; human answers re-enter
  through the gate, which re-evaluates. Versioned prompt files (loader fails loudly on
  unversioned prompts; 11 Turkish few-shot examples for question generation),
  ontology-guided module attribution over the Aurora taxonomy, `estimo-pipeline`
  run/resume CLI, and the `estimo-eval` offline harness asserted in CI — first report:
  module attribution 92% vs 31% naive baseline (+62), zero gate failures, zero
  question gaps (`evals/reports/2026-08-03-s4-offline-eval.md`). Pydantic AI was
  deliberately not adopted (its own model clients would bypass ADR-0001).
- **S3 knowledge layer** (`packages/knowledge`): estimate-ledger Postgres schema
  (migration 0002) with Turkish-FTS generated tsvectors and dimension-flexible
  embeddings (model id + dim recorded per row); seed-set importer
  (`estimo-ledger-import`) implementing the LEDGER-SCHEMA contract — CSV/XLSX header
  aliases, Turkish dates/decimals, bad-row report, unknown-module review queue; hybrid
  retrieval (Turkish lexical with suffix-strip prefix matching + optional dense leg via
  the gateway, RRF fusion, ACL pre-filter on chunks); analogy cards carrying the
  outside view (estimate then vs actual, deviation). Turkish retrieval golden set
  (`evals/golden/retrieval-tr/`) asserted in CI; embedder/reranker shoot-out deferred
  to the first live gateway (ADR-0004 updated with the lexical-leg decision).
- **S2 BRD parsing** (`packages/parse`): Turkish `.docx` BRDs → stable-ID requirement
  tables via Docling's DOCX backend (slim install, no ML models — ADR-0005 scope
  discipline). Extraction ladder: explicit codes → requirement tables (acceptance
  criteria captured) → modal-verb heuristics for messy documents. Anchor quarantine
  detection (budget/deadline/analogy/effort-hint, PRINCIPLES #5), deterministic
  ambiguity pre-score with an optional gateway LLM blend that can only raise the rule
  floor, document-level open-point extraction, and the `estimo-parse` CLI. Golden eval
  in CI asserts every planted anchor/ambiguity in the fixture manifest is caught.
- **S1 skeleton (first code):** uv-workspace monorepo (Python 3.13/3.14) with
  `packages/core` (pydantic domain models that structurally enforce the product laws —
  three-point ranges, evidence-required estimate lines), `packages/gateway` (the single
  OpenAI-compatible client module: stage→profile routing, Retry-After-aware retries,
  metadata-only logging hooks), and `apps/api` (FastAPI: liveness/readiness split,
  run records on Postgres via async SQLAlchemy + Alembic, pgvector enabled in
  migration 0001).
- Fully containerized dev loop per ADR-0006: multi-stage uv Dockerfile (non-root,
  stdlib healthcheck), `compose.yaml` with healthcheck-gated migrate→api ordering and a
  `mock` profile (OpenAI-compatible mock LLM + gateway smoke check).
- CI/CD: lint/typecheck/test workflows (uv, matrix 3.13/3.14, pgvector service),
  provider-SDK and open-core path guards as tested code, multi-arch GHCR publish on
  native arm64 runners with provenance/SBOM attestations, release-please v5,
  semantic PR-title enforcement, dependency review with an ADR-0005 license denylist,
  Dependabot (actions/docker/uv) and CodeQL default setup.
- Design system artifacts under [docs/design/](docs/design/) (hi-fi screens, wireframes,
  tokens — Aurora Telecom installment scenario, light+dark, IBM Plex).
- S0 data foundation: Aurora fixture universe standard
  ([fixtures/README.md](fixtures/README.md)), estimate ledger schema v0 + seed-set import
  contract ([docs/LEDGER-SCHEMA.md](docs/LEDGER-SCHEMA.md)), in-house seed-set inventory
  template ([docs/SEED-SET-INVENTORY.md](docs/SEED-SET-INVENTORY.md)), golden-set &
  metrics design ([evals/README.md](evals/README.md)), synthetic Turkish BRD fixtures
  with planted-feature manifest ([fixtures/brd/](fixtures/brd/)).
- ARCHITECTURE: explicit **ordered indexing pipelines** section (wiki / code / ledger
  lanes + query path); git-hosting connectors named explicitly with **Bitbucket
  first-class** (roadmap S9-2, Admin → Connections).
- ADR-0006: **fully containerized delivery** — every component ships as a multi-arch OCI
  image on GHCR; `docker compose up` is the canonical dev & single-node runtime, Helm
  consumes the same images (roadmap S1-5/S1-8/S7-9 updated).
- ADR-0005: OSS-first composition — adopt proven, license-safe components behind internal
  interfaces; from-scratch code reserved for the differentiation core. Linked from
  AGENTS.md golden rules and ARCHITECTURE.md.

### Fixed
- **Confluence code macros no longer lose text.** CDATA bodies were inlined *before* the
  tag-stripping pass, so everything between a `<` and the next `>` inside a code sample
  was deleted: a rule reading `if (tutar < 100 AND adet > 2)` was indexed as
  `if (tutar 2)`. In a telco BSS wiki that is exactly where the business rules are
  written. CDATA is now held behind sentinels through the whole pipeline and restored
  after entity-unescaping, since a sample's `&amp;` is literal source rather than an
  entity to resolve.
- **Confluence tables keep their rows together.** Storage format wraps cell content in
  `<p>`, so the generic block pass gave every cell its own line and a field table lost
  the association between a field and its type — `musteri_no` and `VARCHAR(20)` on
  separate lines, unsearchable as a pair and meaningless to a human reading the
  retrieved text. Cells are flattened before that pass and `</tr>` is again the only row
  boundary.
- **Adversarial review of the S11 batch: 36 findings raised, 7 survived refutation, two
  of them regressions this same batch introduced.**
- `restricting_audiences([])` returned `{public}`, conflating "every source is public"
  with "there are no sources". Module-wiki `source_ref`s embed the commit SHA, so any
  push to a synced repo prunes the previous sync's chunks — a canonical draft awaiting
  approval could therefore lose every source while its body still held their restricted
  text, and approving it published that body to `public` at the 0.95 authority tier.
  Before the ACL commit the same call raised; the commit written to close a widening
  opened a caller-independent one. Unknown now resolves to refusal, never to public, and
  `approve` additionally refuses when any recorded `source_ref` no longer resolves — the
  body outlives its sources, so the survivors' audience is not a safe answer.
- `embed_pending` called `session.rollback()` on a session it did not own. In `run_sync`
  that expired the caller's ORM objects and silently reverted `SyncRun.status` from
  "succeeded" back to its last committed value, "running" — persisting a finished crawl
  as running, where the one-running-sync partial index blocked the connection until the
  hourly sweep. The most likely trigger was mundane: a deployment with a chat gateway but
  no `embedding` profile raises on every call. The rollback is gone (nothing had been
  written since the previous batch committed) and the embed pass now runs only after the
  run's terminal state is durable.
- The Jira connector rewrote a ledger row's title and description without invalidating
  its vector, so the dense leg kept retrieving the row under text it no longer contained.
- `attribution.product_rows` counted `jira://` rows as rows the product wrote, inflating
  the unattributed denominator with rows nobody was ever asked to attribute.
- `upsert_document` invalidated a row's embedding on **every** write. The Confluence
  lane re-ingests a 26-hour overlap window of unchanged pages on each incremental sync,
  so that would have wiped every vector in the window on each run and re-billed the
  embedder forever to recompute byte-identical text. It now invalidates only when the
  embedded text actually changed — and still does when it did, because a stale vector
  for edited text retrieves confidently against content that no longer says that.

### Security
- **Prefix pruning no longer reaches across connections.** `_` is a LIKE wildcard and the
  connection name is user-supplied (`[A-Za-z0-9._ -]` is allowed at the API boundary), so
  syncing a connection named `a_b` matched — and deleted — the indexed chunks of a
  connection named `axb`. Verified in SQL: `'repo://axb@sha/f' LIKE 'repo://a_b@%'` is
  true. All three prefix matches now use `startswith(..., autoescape=True)`, including
  the two whose inputs cannot currently contain a wildcard: prefix matching that reasons
  about its input each time eventually meets an input it was wrong about.
- **Editing a Confluence page no longer leaves its previous version retrievable.** A
  Confluence `source_ref` embeds the page version (`wiki://{id}@{n}`), so every edit
  wrote a new chunk — and nothing ever removed the old one. The git lane has pruned by
  prefix since S9; this lane never did. Superseded text therefore stayed searchable
  indefinitely, *carrying the ACL it had at the time*: restricting a page at the source
  had no effect on the version that was public, which is the pre-filter silently
  serving content the source system had already locked. The lane now prunes every other
  version of a page as it ingests the current one.
- **`GET /v1/canonical` filters by the caller's audience (S11-7 complete).** Clamping the
  sourcing path stopped a reviewer pulling restricted text into a *new* draft; it did
  nothing about pages an entitled curator had already published, whose bodies every
  reviewer in the tenant could still read back. A canonical body is a distillation of its
  sources' text and inherits their audience, so the list now derives that audience — the
  published chunk's ACL for an approved page, the sources' common audience for a draft —
  and omits pages the caller shares nothing with. A page whose sources were pruned has an
  audience that cannot be computed; unknown means withheld, so the row is listed with
  `sources_missing: true` and no body, which is also what a curator needs to see in order
  to regenerate it.
- **`GET /v1/estimates/{id}/desk` no longer mutates.** It flipped the caller's
  `revealed` flag, wrote a `draft-revealed` event and emitted the anchoring delta —
  from a read. A link prefetch, a crawler, or anyone passing a colleague's name in the
  `estimator` query string could therefore consume that colleague's un-revealed state
  permanently (bands are immutable) and write an anchoring sample for a reveal that
  never happened to a person who never saw it, corrupting the very measurement
  PRINCIPLES #4 exists to produce. The reveal now belongs to `POST /independent`, the
  deliberate act that earns it: committing your own number is the moment anchoring
  protection ends, and the number recorded is identical. Guarded by a regression test
  verified in both directions — it fails if recording stops emitting, and it fails if
  reading starts.
- **The ACL pre-filter no longer takes its permissions from the requester.**
  `POST /v1/canonical` passed the request body's `acl_keys` straight into
  `lexical_chunk_ids`, so any reviewer could name a restricted audience, have its text
  distilled into a draft body, and read that body back from `GET /v1/canonical` — which
  returns page bodies to every reviewer in the tenant. `Principal` now carries the
  audiences Estimo can actually attribute to a caller (from `ESTIMO_AUTH__ACL_CLAIM`),
  and `clamp_acl_keys` treats a requested key list as a *narrowing preference over that
  set*, never as a grant. Unset claim, or single-tenant open mode, means public-only —
  a pre-filter that cannot identify its reader must show less, not more (SECURITY.md).
  The synthetic open-mode principal deliberately does **not** inherit every audience
  along with every role: ACL keys model the *source* system's permissions, and Estimo's
  users are a superset of who may read a restricted Confluence space.
- **Approving a canonical page can no longer widen it.** Explicit `acl_keys` overrode
  the computed source intersection outright, so text distilled from a restricted space
  could be published to a wider audience — the same widening the pre-filter prevents,
  applied at write time. Explicit keys may now only narrow. Fixing this exposed why the
  override existed: the intersection treated `public` as a constraint, so one public
  source plus one restricted source looked unpublishable when the correct audience is
  simply the restricted one. `restricting_audiences` (in `estimo_core`, shared by the
  API clamp and the publish clamp) now excludes universally-held keys, and genuinely
  disjoint audiences stay unpublishable together.
- **S10 review hardening** (adversarial review; 10 confirmed findings fixed): the MCP
  endpoint is now an OAuth2 resource server (FastMCP `JWTVerifier`) that pins the
  caller's tenant from the validated token — it was reachable unauthenticated and read
  the default tenant. Unique keys on tenant tables are composite with `tenant_id`
  (migration `0010`) so one tenant's write can no longer collide with, overwrite, or
  probe another's. Helm: the API/migration split onto the right DB roles (RLS was
  bypassed by connecting as the owner), the migration moved to an init container (the
  hook ran before the bundled Postgres existed), and the bundled password is reused
  across upgrades instead of regenerated. Cross-tenant system paths take an optional
  owner connection; the sync trigger self-heals orphaned `running` rows. Role claims
  accept a space-delimited string (a bare string was iterated per character, silently
  denying every role).
- **S9 review hardening** (adversarial review; 28 confirmed findings fixed): the ACL
  pre-filter provably never widens — Confluence connections require explicit
  `space_keys`, read restrictions resolve by walking ancestors (inheritance), and
  canonical approval publishes the intersection of its sources' ACL keys (refusing
  mixed-audience defaults). Connection names are slugged before becoming filesystem
  paths (no `../` escape). Also: one-running-sync-per-connection is DB-enforced
  (migration `0008`), interrupted runs are swept at startup, pagination follows
  `_links.next` verbatim (no cursor double-encoding), the incremental watermark uses
  real datetimes with a 26h overlap, deleted source modules are pruned from
  retrieval, and GitLab signed webhooks enforce a replay window.
- **S7 review hardening** (adversarial review; 14 confirmed findings fixed):
  independent-first now holds across the WHOLE API surface — `GET /{id}`, the build
  response and the `.docx` export withhold the draft body until every line is signed,
  and signing itself requires the signer's own revealed band. BoE drafts are
  **versioned** (migration `0005`): reveals, sign-offs and anchoring telemetry are
  bound to the draft they were recorded against, so a rebuild never inherits them,
  and rebuilding over a live draft is refused. Also: upload size limit enforced while
  streaming; `Content-Disposition` uses an ASCII slug + RFC 5987 `filename*` (no
  header injection, no non-latin-1 500s); server-reserved telemetry kinds are not
  forgeable; empty answers no longer close questions; `.dockerignore` patterns fixed
  so nested env files and Node artifacts stay out of build contexts.

### Changed
- **Doc-truth pass #2**, from scoping the S11 items against the code. The first pass fixed
  claims that were *overstated*; this one fixes claims that were *wrong*. Retrieval is
  **lexical in practice everywhere**: nothing in the repo writes an embedding — the only
  `.embed()` call embeds the query, and `upsert_document` NULLs the vector columns on every
  write — so `dense_ledger_ids` matches zero rows and RRF fuses a single ranking. There is
  also no chunker: a Confluence page becomes one `knowledge_chunks` row, so "chunk" is
  currently a misnomer for "document". ARCHITECTURE.md said otherwise in three places
  (component table, wiki lane, query path) and now says this. The S11-4 blocker recorded
  yesterday was itself wrong — `ledger_entries` has carried `team` and `domain_tags` since
  migration 0002. Added S11-8 for the missing embedding writer, split S11-6 into the docs
  site (decided against, with the reasoning) and the Marketplace assessment (blocked on the
  deferred Forge surface), and recorded the sourcing escalation found under S11-7.
- CONTRIBUTING.md told contributors "the repo is documentation-only and the only build is
  reading docs/RESEARCH.md" — ten sprints after that stopped being true. It now carries the
  real gates (uv sync, ruff, mypy, pytest, the separate npm build for `apps/web`). AGENTS.md
  named a `packages/calibrate/` that has never existed, omitted `code/` and `estimate/`,
  labelled the web app "Türkçe-first" in an English document and called the translated
  research dossier Turkish. docs/DEPLOY.md had no inbound link from any navigable page and
  is now in the README map.
- **The web UI now implements the delivered design system**, not just its colour
  tokens (`docs/design/estimo-ui.dc.html`). Ported: the full token set (surfaces,
  ink tiers, two-tier borders, status and evidence roles, shadows), both density
  modes, IBM Plex Sans/Mono/Serif self-hosted at build time, and the component
  layer (`.dt` · `.card` · `.chip` · `.btn`/`.btn.p` · `.rail-i` · `.stg` · `.ph` ·
  `.lbl`/`.num`/`.mn`). Bespoke components implemented as the design specifies them:
  **RangeBar** (three-point band with the overhanging likely marker), **EvidenceChip**
  (a third colour role), **StatusChip** where **shape carries state alongside colour**
  (circle = good, diamond = warning, square = critical), and the **StageStrip**.
  The app now has the design's chrome — sticky top bar with theme/density toggles and
  the 184px left rail — and its screens: Workspace, Reading Room, Question Board,
  **Impact Map**, Estimate Desk (with the honest closed state — never a blurred
  reveal), BoE Preview & Signature, **Ledger & Analog Search** (new,
  `GET /v1/ledger`), Calibration Dashboard, Knowledge Curation, and Admin.

#### Earlier
- Project renamed from **Eforge** to **Estimo** (briefly Lodestar) — from the Latin
  *aestimo*, "I estimate, I appraise".
- **English is now the repository's single language**: the research dossier, roadmap and
  UI vision were translated; Turkish remains as *data only* (synthetic BRD fixtures,
  retrieval benchmarks, `tr` localization templates). ADR-0004 revised to
  "English-first product, Turkish-first input"; AGENTS.md language policy updated.
- ADR-0005 gained an explicit **credibility bar**: only de-facto-standard,
  major-org-backed, or overwhelmingly adopted OSS projects qualify as dependencies.
- README is now English-only (Turkish summary section removed).

## [0.1.0] - 2026-08-03

### Added
- Founding research dossier ([docs/RESEARCH.md](docs/RESEARCH.md)): market gap analysis,
  evidence review on LLM-based effort estimation, reference architecture, telco domain
  layer, and open-source stack survey — synthesized from a 5-track parallel research run.
- Repository foundation: README, Apache-2.0 license, agent guide ([AGENTS.md](AGENTS.md)),
  contributor guide, security & data-handling policy, code of conduct.
- Product principles ([docs/PRINCIPLES.md](docs/PRINCIPLES.md)) — evidence-derived rules
  every feature must respect (ranges over points, evidence links, anchoring protection).
- Architecture reference ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) and initial ADRs
  (LiteLLM-only gateway, Atlassian-adjacent core, Apache-2.0, Turkish-first pipeline).
- Trackable sprint roadmap ([docs/ROADMAP.md](docs/ROADMAP.md)).
- UI vision brief ([docs/UI-VISION.md](docs/UI-VISION.md)) — input for the design-system pass.
