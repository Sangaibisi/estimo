/** Estimo UI strings — English only.
 *
 * The product interface is deliberately single-language (English), matching the
 * repo language policy. Turkish remains a DATA language (ADR-0004): BRD inputs,
 * fixtures and the exported BoE artefact keep their Turkish content — rendered by
 * the backend, not by this file. The old locale toggle and `tr` dictionary were
 * removed with the 2026-08 UI redesign.
 */

const M = {
    appTitle: "Estimo",
    tagline: "Evidence-linked effort estimation",
    estimates: "Estimates",
    ledger: "Ledger",
    calibration: "Calibration",
    knowledge: "Knowledge",
    admin: "Admin",
    themeDark: "Dark theme",
    themeLight: "Light theme",
    stageReading: "1 Reading",
    stageQuestions: "2 Questions",
    stageImpact: "3 Impact",
    stageEstimate: "4 Estimate",
    stageBoe: "5 BoE",
    independentHeadline:
      "You first. The draft stays closed until you enter your own range.",
    independentBody:
      "Nothing is blurred behind this panel — we are not hiding a number from you, we simply have not shown you ours yet.",
    closed: "closed",
    delphiLabel: "Delphi overlay",
    delphiCaption:
      "The width of the disagreement is the finding — not the average.",
    delphiYouFirst: "record yours to see the panel",
    delphiBelow: "{have} of {need} recorded",
    delphiSpread: "spread",
    delphiIntersect: "ranges intersect",
    delphiDisjoint: "disjoint — discuss",
    delphiConsensus: "consensus",
    teamPlaceholder: "team (optional)",
    yourRange: "Your range — O · L · P",
    draft: "Draft",
    lineItem: "Line item",
    entered: "entered",
    subtotal: "Your subtotal",
    signatures: "signatures",
    dropBrd: "Drop a .docx BRD here",
    orBrowse: "or browse — 20 MB max",
    inFlight: "in flight",
    waitingCustomer: "waiting on the customer",
    noEvidenceNoLine: "No line item without evidence.",
    workspaceSubtitle:
      "Every estimate in flight — stage, open questions, and who is waiting.",
    newEstimate: "New estimate",
    firstRead: "First read",
    file: "File",
    stage: "Stage",
    items: "Items",
    itemOne: "item",
    openQ: "Open Q",
    waitingOn: "Waiting on",
    keyboardHint:
      "An estimate opens on its Reading Room; the desk stays closed until you enter your own range.",
    stateDraftClosed: "Draft closed — you first",
    stateDraftRevealed: "State B — draft revealed",
    stateNoDraft: "No draft yet",
    reviewer: "Reviewer",
    anchorsShort: "Anchors",
    clear: "clear",
    laneOpen: "Open",
    laneSent: "Sent",
    laneEmpty_open: "Nothing waiting on you.",
    laneEmpty_sent: "Nothing is out with the customer.",
    laneEmpty_answered: "No answers waiting to be folded in.",
    laneEmpty_applied: "No answer has changed the estimate yet.",
    laneAnswered: "Answered",
    laneApplied: "Applied",
    waitingDays: "waiting {n}d",
    recordAnswer: "Record answer",
    answerFrom: "answer from…",
    answeredBy: "who answered",
    applyToLine: "Apply to line item",
    appliedTo: "Applied to",
    reEstimateSuggested: "Re-estimation suggested",
    sendSelected: "Send selected",
    recipientPlaceholder: "customer contact",
    newQuestion: "New question",
    questionPlaceholder: "the question to ask",
    downloadLetter: "Download .docx",
    letterHint:
      "Selected questions compile into one message in the estimate's locale, formal register.",
    emptyQuestions: "Every requirement passed the gate — a good sign.",
    customerSet: "Customer set",
    selectedShort: "selected",
    composerHint:
      "Tick the questions to send; the letter below is what the customer receives.",
    openPoints: "Open points",
    selectToCompose: "Tick a question to compose the letter.",
    copyText: "Copy text",
    impactShort: "Impact",
    viewGraph: "Graph",
    viewHeat: "Heat list",
    impactFootnote:
      "Uncertainty is not hidden here — it is priced on the desk.",
    evidenceFor: "Evidence",
    wikiSection: "Wiki",
    analogSection: "Analog jobs",
    codeSection: "Code references",
    noCodeGraph:
      "No repository is connected, so code references cannot be shown — add a git connection in Admin.",
    confHigh: "high confidence",
    confMedium: "medium",
    confLow: "low",
    discoverySuggested: "discovery effort suggested",
    selectModule: "Select a module to see what grounds its mapping.",
    coverageHidden:
      "Evidence coverage is hidden once a draft exists — it would disclose the closed band.",
    unmappedModule: "(unmapped)",
    unmappedHint: "The decomposer could not attribute these to a module.",
    noEvidenceForModule:
      "Nothing retrieved for this module — the mapping rests on naming alone.",
    estimatedShort: "estimated",
    impactSubtitle: "Which modules this BRD lands on, by work items touched.",
    openDesk: "Open desk",
    deskClosedHint:
      "Enter your name and open the desk — the draft stays closed until you record your own range.",
    likelyShort: "likely",
    range: "Range",
    boeTitle: "Basis of Estimate",
    exportSection: "Export",
    contentsRail: "Contents",
    secScope: "1 Scope & exclusions",
    secLines: "2 Line items",
    secAssumptions: "3 Assumption register",
    secRisks: "4 Risks & contingency",
    secCone: "5 Cone stage",
    secProvenance: "6 Provenance appendix",
    secSignature: "7 Signature page",
    signatureFlow: "Signature flow",
    rowsYouApprove: "Rows you are approving",
    signRowsBtn: "Sign {n} rows",
    signScopeHint:
      "Your signature names exactly the rows it covers. Anything you did not sign stays unsigned.",
    afterSigning: "After signing",
    afterSigningBody: "Any change afterwards opens a new version with a diff.",
    versionHistory: "Version history",
    "note-first-draft": "first draft",
    "note-rebuilt-after-answers": "rebuilt after answers",
    "note-snapshot taken at migration 0014":
      "snapshot taken when history began",
    sectionAbsent: "This estimate does not carry that section.",
    diffsWithheld:
      "{n} diff withheld — a version nobody signed cannot be compared without disclosing it.",
    signedConfirmation: "BoE v{n} signed — ready to export.",
    authoritySigns: "Sign as signing authority",
    pendingAuthority: "Pending — signing authority",
    diffWidened: "widened",
    diffNarrowed: "narrowed",
    diffShifted: "shifted",
    diffAdded: "added",
    diffRemoved: "removed",
    noChange: "no line changed",
    scopeSectionMissing:
      "Scope & exclusions is not produced by the pipeline yet — the estimate states what it covers through its line items.",
    provenanceIntro: "Every line cites the evidence it was built on.",
    notSignedYet: "not signed yet",
    noDraftYet: "No draft yet — build one on the Estimate stage.",
    ledgerSubtitle:
      "What similar work actually cost, and how far the estimate was off.",
    entriesWord: "entries",
    withActuals: "with actuals",
    analogSearchPlaceholder: "Search analogs — e.g. taksitli fatura",
    search: "Search",
    clearSearch: "Clear",
    analogRankHint:
      "Ranked by the same retrieval the estimator reads — outcome feedback included.",
    ledgerEmpty: "The ledger is empty — import the seed set or record actuals.",
    modules: "Modules",
    estimateGiven: "Estimate given",
    source: "Source",
    ledgerFootnote:
      "Scope-changed rows are kept for honesty but excluded from calibration.",
    allTeams: "All teams",
    allDomains: "All domains",
    teamWord: "Team",
    domainWord: "Domain",
    cadenceLabel: "Sync every (min)",
    minShort: "min",
    cadenceOff: "manual",
    pinPlaceholder: "Page ID / issue key",
    pinNow: "Pin",
    allDisciplines: "All disciplines",
    disciplineWord: "Discipline",
    frontendWord: "Frontend",
    backendWord: "Backend",
    disciplineSplit: "Discipline split",
    modelProposedBadge: "model-proposed, uncalibrated",
    historicalRatioBadge: "historical ratio",
    deliveredWord: "Delivered",
    rangeThatDay: "Range that day",
    boeRowColumn: "BoE row",
    openWord: "open",
    lexicalOnlyHint:
      "No similarity measured — either the dense retrieval leg did not run, or these entries carry no embeddings yet.",
    similarityWord: "match",
    importSeedSet: "Import seed set",
    seedImportTitle: "Seed set import",
    stepOf: "step {n} of 4",
    chooseFile: "Choose a CSV or XLSX file",
    mapTheColumns: "Map the columns",
    unmappedWord: "unmapped",
    doNotImport: "do not import",
    missingRequired: "Required columns are unmapped: {fields}",
    beforeAnythingEnters: "Before anything enters",
    checkNoPersonalData: "No personal data in free-text fields",
    checkCustomersAnonymised: "Customer names anonymised",
    checklistBlocks:
      "Both boxes have to be true. The server refuses the import until they are confirmed.",
    startImport: "Import",
    importingWord: "Importing…",
    importDone: "{imported} of {total} rows imported",
    reviewFailedRows: "Review failed rows",
    failedRowsQueue:
      "{n} rows were rejected and did not enter the ledger. Fix them in the file and import it again — this list is not kept after you close the wizard.",
    noActualsNote:
      "{n} rows imported without actuals. They are kept, but calibration cannot use them until an actual lands.",
    reviewQueueModules: "Modules the ledger has not seen before",
    parseWarnings: "Values that could not be read",
    duplicatesNote:
      "{n} rows were already in the ledger and were skipped — importing them again would count the same job twice.",
    noMatchHere:
      "Nothing matches this search or filter. The ledger itself is not empty.",
    rowWord: "row",
    startOver: "Import another file",
    cancelWord: "Cancel",
    backWord: "Back",
    nextWord: "Next",
    calibrationSubtitle: "Are our ranges honest? The product grades itself.",
    exportFigures: "Export figures",
    windowAll: "All time",
    windowMonths: "Last {n} months",
    perSliceTitle: "Coverage by team and domain",
    perSliceHint:
      "One bar per slice, drawn only where enough closed jobs exist to mean anything.",
    sliceWithheld: "{n} of {need} closed jobs — too few to state a rate",
    worstSlice:
      "{key} sits at {value} across {n} closed jobs — under target. We are not adjusting the target to match.",
    noSlicesYet:
      "No slice has enough closed jobs yet. Attribution is supplied when an actual is recorded — a BRD never says which team will do the work.",
    unbandedNote:
      "{n} completed items carried a single number rather than a range, so they cannot be graded.",
    mapeTitle: "Percentage error",
    mapeExcluded:
      "{n} items under 2 pd excluded — a half-day miss there is 50%.",
    pBelowFloor: "< 0.0001",
    verdictNotDistinguishable:
      "On this dataset the difference is not meaningful ({wins} wins / {losses} losses, p={p}). We say so rather than round it into a win.",
    verdictPipelineBetter:
      "The pipeline beat the baseline on {wins} of {decided} items (p={p}).",
    verdictBaselineBetter:
      "The baseline beat the pipeline on {losses} of {decided} items (p={p}). Stated as plainly as a win would be.",
    verdictNoSignal:
      "Not enough completed items to compare against the baseline yet.",
    entryBlind: "Recorded while the draft was hidden",
    entryAfterReadable: "Recorded once the draft was readable",
    entryUnknown: "Recorded before this was tracked",
    entryHint:
      "The desk withholds the draft until a band exists — but a fully signed draft is readable through the API and the .docx, and a band entered after that cannot testify about anchoring.",
    questionImpactTitle: "Question impact",
    questionImpactHint:
      "Measured by comparing frozen draft versions: only lines that gained an answer as evidence are counted.",
    changedShare: "of answered questions changed a line's range",
    widthChange: "median range width once an answer lands",
    linesCreated:
      "{n} answers produced a new line rather than moving one — counted apart.",
    questionImpactEmpty:
      "No answer yet landed on an estimate that already had a draft. The gate refuses to build over an open question, so most answers arrive before the first draft — there is nothing to compare.",
    reasonsTitle: "What raised the questions people answered",
    howHonest: "Interval honesty",
    completedItems: "completed items",
    coverageVsTarget:
      "We captured actuals inside the range {actual} of the time against a target of {target}.",
    noCoverageYet: "no completed items yet",
    transferQuantiles: "Transfer-error quantiles",
    priorBased: "cold-start prior — not your history yet",
    anchoringSection: "Anchoring & workflow",
    anchoringSubtitle:
      "Independent bands should rarely match the draft; rework should not grow while drafting speeds up.",
    nominalWord: "nominal",
    naiveMedian: "naive (median)",
    knowledgeSubtitle:
      "Candidate pages reviewed against their sources, then published with a version.",
    queueWord: "Queue",
    driftedWord: "Drifted",
    publishedWord: "Published",
    candidateQueue: "Candidate queue",
    noCandidates: "No candidates yet — generate one from a topic.",
    newCandidate: "New candidate",
    sourceWord: "Source",
    pagesMerged: "sources merged",
    noSources: "No sources recorded for this candidate.",
    candidateDistilled: "Candidate · distilled",
    approvePublish: "Approve & publish",
    versionFootnote:
      "Publishing is versioned. Every estimate cites the page version it actually read.",
    selectCandidate: "Pick a candidate to review it against its sources.",
    adminSubtitle: "Boring but transparent: sync status, error queues, roles.",
    connections: "Connections",
    addConnection: "Add connection",
    connected: "connected",
    errorWord: "error",
    firstSync: "first sync",
    neverSynced: "never synced",
    lastSyncAgo: "Last sync",
    rolesSection: "Roles & signing authorities",
    roleAnalyst: "Estimator",
    roleReviewer: "Reviewer",
    roleSigning: "Signing authority",
    roleAdmin: "Admin",
    maySign: "May sign",
    maySignNothing: "—",
    maySignLines: "line items",
    maySignFull: "full BoE",
    firstSyncHint:
      "Indexing — a large wiki can take days. You can keep working while it runs.",
    rolesFootnote:
      "Roles come from your identity provider's token claim; Estimo never stores a user list.",
    upload: "Upload BRD (.docx)",
    uploading: "Parsing…",
    status: "Status",
    requirements: "Requirements",
    blocked: "Blocked",
    openQuestions: "Open questions",
    workItems: "Work items",
    questionsTab: "Questions",
    deskTab: "Estimate Desk",
    boeTab: "BoE",
    requirementsTab: "Requirements",
    answerPlaceholder: "Customer answer…",
    applyAnswers: "Apply answers",
    buildBoe: "Build BoE draft",
    estimatorName: "Your name",
    independentHint:
      "Independent-first: enter your own band before the AI draft is revealed for an item.",
    record: "Record my band",
    yourBand: "Your band",
    aiBand: "AI draft",
    delta: "Δ likely",
    sign: "Sign line",
    signed: "Signed",
    downloadDocx: "Download BoE (.docx)",
    total: "Total",
    confidence: "Confidence",
    evidence: "Evidence",
    critic: "Critic findings",
    noEstimates: "No estimates yet — upload a BRD to start.",
    copyQuestions: "Copy customer question set",
    anchors: "Quarantined anchors (visible to humans, hidden from models)",
    ambiguity: "Ambiguity",
    idHeader: "ID",
    textHeader: "Text",
    signAllFirst:
      "The export contains every band — sign all lines on the desk to unlock it.",
    actualsTab: "Actuals",
    actualsHint:
      "Recorded actuals feed the ledger: analog ranking and interval calibration learn from them.",
    actualEffort: "Actual (pd)",
    actualSource: "Source",
    scopeChanged: "Scope changed",
    save: "Save",
    revise: "Revise",
    deviationLabel: "Deviation",
    actualsAfterSignoff:
      "Actuals are recorded against the fully signed estimate of record.",
    dashboard: "Dashboard",
    coverageChartTitle: "Interval coverage vs nominal",
    coverageChartHint:
      "Rolling coverage of the last 20 completed items; dashed line = nominal.",
    maeChartTitle: "MAE — product vs naive median",
    maeChartHint: "Mean absolute error on completed items; lower is better.",
    anchoringTile: "Mean |Δ likely| at reveal",
    zeroDeltaTile: "Near-zero delta share",
    zeroDeltaHint:
      "High values suggest anchoring — independent bands should rarely match the AI.",
    wipTile: "Estimates in progress",
    revisionTile: "Question revision rate",
    rebuildTile: "Rebuild share",
    samplesShort: "n",
    lowSampleNote:
      "Small sample — coverage within ±5% needs ~100 completed items.",
    noData: "No data yet — record actuals to light this up.",
    tableView: "Data table",
    connectionsTitle: "Connections",
    newConnection: "New connection",
    connectionName: "Name",
    secretEnvHint:
      "Paste the credential to store it sealed in the database (encrypted when ESTIMO_SECRET_KEY is set) — or leave it empty and give the NAME of an env var on the API container instead.",
    secretValuePlaceholder: "credential / token (stored sealed)",
    orEnvVar: "or env var name",
    aclKeysPlaceholder: "ACL keys (comma-separated)",
    lastSync: "Last sync",
    syncNow: "Sync now",
    secretMissing: "secret env missing",
    canonicalTitle: "Canonical pages",
    canonicalHint:
      "The LLM drafts candidates from existing knowledge; only human-approved pages enter retrieval (top authority).",
    canonicalTopic: "Topic…",
    generateCandidate: "Generate candidate",
    approve: "Approve",
    staleSource: "stale",
    deleteConnection: "Delete connection",
    confirmDeleteConnection: "Delete connection “{name}” and its sync history?",
    gatewaySection: "Model gateway",
    gatewayHint:
      "Every model call flows through this one OpenAI-compatible endpoint — LiteLLM in production. Env vars are only bootstrap defaults: what you save here overrides them immediately, no restart.",
    saveGateway: "Save",
    revertEnv: "Revert to environment",
    clearGateway: "Remove gateway",
    clearGatewayConfirm:
      "There is no gateway in the environment to fall back to, so this removes the model gateway entirely. Parsing, the ambiguity gate, decomposition, questions and calibrated bands keep working; the model-assisted steps stop. Continue?",
    gatewayUnset: "no model gateway yet",
    gatewayUnsetHint:
      "Nothing is configured, and the product still runs: parsing, the ambiguity gate, decomposition, questions and calibrated bands are all deterministic. Set an endpoint here to switch the model-assisted steps on.",
    sourcePanel: "configured in panel",
    sourceEnv: "from environment",
    apiKeyLabel: "API key",
    apiKeySavedPlaceholder: "•••• saved — leave empty to keep",
    apiKeyUnsetPlaceholder: "paste the gateway API key",
    baseUrlLabel: "Base URL",
    addProfile: "Add profile",
    unencryptedWarn:
      "stored secrets are NOT encrypted — set ESTIMO_SECRET_KEY on the API",
    keyUnreadable:
      "the stored API key will not unseal (ESTIMO_SECRET_KEY rotated or unset) — calls are using the environment key; re-enter it below",
    savedOk: "saved — effective immediately",
    stageHeader: "Stage",
    profileHeader: "Model profile",
    keyConfigured: "API key configured",
    keyMissing: "API key missing",
    noProfiles: "No profiles configured — every model call will fail.",
    noProfilesYet:
      'Add one row per stage once you have an endpoint (start with "default").',
    testGateway: "Test gateway",
    testing: "Testing…",
    gatewayOk: "round-trip ok",
    timeoutShort: "timeout",
    retriesShort: "retries",
    runtimeSection: "Runtime & authentication",
    authModeLabel: "Auth mode",
    authModeOpen: "open — single tenant, every caller holds every role",
    authModeOidc: "OIDC",
    aclClaimUnset: "no ACL claim — restricted sources stay public-only",
    apiVersionLabel: "API version",
    databaseLabel: "Database",
    corsLabel: "CORS origins",
    envOnlyHint:
      "Auth, database and CORS stay environment-only by design — a bad auth save would lock every admin out of this panel. Change those env vars and restart; the gateway and connection credentials are editable above.",
    coneStage: "Cone stage",
    coneConcept: "Concept stage",
    coneApproved: "Approved scope",
    coneDetailed: "Detailed",
    coneNarrows: "Narrows once the open questions are answered.",
    sourcePane: "Source",
    sourceUnavailable:
      "This BRD was parsed before the source pane existed — re-upload it to read the document here.",
    sourceTruncated: "long document — some passages are not shown",
    sourceFailed: "The source could not be loaded — try again.",
    sourceRowMissing: "this row's passage is not in the shown extract",
    requirementsCount: "Requirements · {n} extracted",
    ambClear: "clear",
    ambPartial: "partial",
    ambAmbiguous: "ambiguous",
    selectRowHint: "Select a row to highlight its paragraph — and back again.",
    markClear: "Mark as clear",
    sendToBoard: "Send {n} to Question Board",
    tableBlock: "Table",
    reqHeader: "REQ",
    statusHeader: "Status",
    statusDraft: "draft",
    statusReviewed: "reviewed",
    statusBlocked: "blocked — open question",
    rationaleLabel: "Your rationale",
    rationalePlaceholder: "why this band (optional)",
    rationaleHint: "Type, or drag the bar. A rationale line is optional here.",
    heldHeadline: "Held — the evidence is missing and a question is open.",
    discoveryChip: "+ discovery",
    weakEvidence: "weak evidence",
    weakEvidenceBody:
      "Evidence is weak on this item — discovery effort is carried as contingency beside the range, not inside it.",
    deltaIntersect: "ranges intersect",
    deltaDisjoint: "disjoint — discuss",
    skipItem: "Skip this item",
    stgRead: "Read",
    stgQ: "Q",
    stgImpact: "Impact",
    stgEst: "Est",
    stgBoe: "BoE",
    devWithin: "within",
    devAbove: "above",
    devBelow: "below",
    quarantined: "quarantined",
    anchorTooltip:
      "This information is hidden from the estimation engine (anchor protection).",
    confidenceHeader: "Confidence",
    arHeader: "A / R",
    assumptionsWord: "Assumptions",
    risksWord: "Risks",
    analogMatches: "Analog matches",
    closedJobsSuffix: "closed jobs",
    estimatedWord: "estimated",
    actualWord: "actual",
    assumptionRegister: "3 · Assumption register",
    risksContingency: "4 · Risks & contingency",
    contingencyNote: "not included in the total",
    draftWord: "draft",
    pendingSignature: "pending signature",
} as const;

export type MessageKey = keyof typeof M;

export function t(key: MessageKey): string {
  return M[key];
}

/** One fixed date locale so timestamps read the same on every workstation
 * (day-first, 24h — the deployment audience convention). */
export const DATE_LOCALE = "en-GB";

const statusLabels: Record<string, string> = {
    awaiting_answers: "Awaiting answers",
    ready_for_estimation: "Ready for estimation",
    boe_draft: "BoE draft",
};

export function statusLabel(status: string): string {
  return statusLabels[status] ?? status;
}

/** Ambiguity issue slugs → the reason sentence the design shows.
 *
 * The gate emits stable slugs (`missing-acceptance-criteria`, `vague-terms:x,y`);
 * "partial" or a bare slug tells a reader nothing they can act on, and the design's
 * Reading Room states the finding as a sentence. The mapping lives here because the
 * slug is the contract and the prose is presentation — a new slug simply falls back
 * to itself rather than disappearing.
 */
const issueSentences: Record<string, string> = {
    "missing-acceptance-criteria":
      "No acceptance criteria — there is no stated condition for calling this done.",
    "implicit-acceptance-only":
      "Acceptance is implied, never written down; the criterion has to be confirmed.",
    "undefined-condition-outcome":
      "A condition is stated but its outcome is not — the expected behaviour is missing.",
    "vague-terms": "Vague wording that admits more than one reading.",
    "unstructured-source":
      "Extracted from prose rather than a numbered requirement, so the boundary is uncertain.",
    "llm-gate-divergence":
      "The rule gate and the model gate disagreed on this row — a human should settle it.",
    "llm-output-unparseable":
      "The model's gate answer could not be read; the rule score stands alone.",
};

/** A gate issue as a sentence. `vague-terms:uygulanabilir,farklı` keeps its detail. */
export function issueSentence(issue: string): string {
  const [slug, detail] = issue.split(/:(.+)/);
  const sentence = issueSentences[slug];
  if (!sentence) return issue;
  return detail ? `${sentence} (${detail.split(",").join(", ")})` : sentence;
}
