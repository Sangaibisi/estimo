"use client";

/** The estimate workspace: five stages from the design system —
 *  2 · Reading Room · 3 · Question Board · 4 · Impact Map · 5 · Estimate Desk ·
 *  6 · BoE Preview & Signature.
 *
 * Design laws honoured here: the desk shows an HONEST CLOSED STATE (never a blurred
 * reveal), status is shape+colour, every quantity is a range (never one number), and
 * exactly one primary action per region. */

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  CONE_MULTIPLIER,
  parseEffort,
  type ActualEntry,
  type DeskItem,
  type DocBlock,
  type EstimateSummary,
  type QuestionLetter,
  type HeldRequirement,
} from "@/lib/api";
import { detectLocale, issueSentence, t, type Locale } from "@/lib/i18n";
import {
  BandHeader,
  Chip,
  EvidenceChip,
  Lbl,
  Mn,
  Num,
  RangeBar,
  StageStrip,
  DelphiOverlay,
  StatusChip,
} from "@/components/ui";
import { IconEstimates } from "@/components/icons";

interface Question {
  id: string;
  requirement_id: string;
  question: string;
  reason: string;
  status: "open" | "sent" | "answered" | "applied";
  answer?: string | null;
  sent_at?: string | null;
  recipient?: string | null;
  answered_at?: string | null;
  answered_by?: string | null;
  applied_to?: string | null;
}

interface Requirement {
  id: string;
  text: string;
  source_ref?: string | null;
  ambiguity_score?: number | null;
  ambiguity_issues?: string[];
  anchors?: { type: string; snippet: string }[];
}

interface WorkItemShape {
  id: string;
  title: string;
  module_tags: string[];
  requirement_ids: string[];
}

interface StateShape {
  requirements: Requirement[];
  questions: Question[];
  answers: Record<string, string>;
  blocked_ids: string[];
  work_items: WorkItemShape[];
}

interface RegisterEntry {
  text: string;
  contingency_pd?: number | null;
}

interface BoeLineShape {
  work_item_id: string;
  range: { optimistic: number; likely: number; pessimistic: number };
  assumptions?: RegisterEntry[];
  risks?: RegisterEntry[];
}

interface BoeDocShape {
  lines?: BoeLineShape[];
  global_assumptions?: RegisterEntry[];
  global_risks?: RegisterEntry[];
}

type StageKey = "reading" | "questions" | "impact" | "desk" | "boe";

export default function EstimateWorkspace({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [locale, setLocaleState] = useState<Locale>("en");
  const [summary, setSummary] = useState<EstimateSummary | null>(null);
  const [state, setState] = useState<StateShape | null>(null);
  const [stage, setStage] = useState<StageKey>("reading");
  const [estimator, setEstimator] = useState("");
  const [deskItems, setDeskItems] = useState<DeskItem[]>([]);
  const [held, setHeld] = useState<HeldRequirement[]>([]);
  const [sourceBlocks, setSourceBlocks] = useState<DocBlock[]>([]);
  const [sourceAvailable, setSourceAvailable] = useState(true);
  const [sourceTruncated, setSourceTruncated] = useState(false);
  const [sourceError, setSourceError] = useState(false);
  const [coneStage, setConeStage] = useState<string | null>(null);
  const [critic, setCritic] = useState<string[]>([]);
  const [fullySigned, setFullySigned] = useState(false);
  const [boeDoc, setBoeDoc] = useState<BoeDocShape | null>(null);
  const [actuals, setActuals] = useState<ActualEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setLocaleState(detectLocale()), []);

  const refresh = useCallback(async () => {
    const detail = await api.getEstimate(id);
    setSummary(detail.summary);
    setState(detail.state as unknown as StateShape);
    setCritic(detail.critic);
    setFullySigned(detail.fully_signed);
    setBoeDoc((detail.boe as BoeDocShape | null) ?? null);
  }, [id]);

  useEffect(() => {
    refresh().catch((err) => setError(String(err)));
  }, [refresh]);

  const loadDesk = useCallback(async () => {
    if (!estimator) return;
    const desk = await api.desk(id, estimator);
    setDeskItems(desk.items);
    setHeld(desk.held);
    setConeStage(desk.cone_stage);
  }, [id, estimator]);

  // The document body is fetched only when the Reading Room is actually open — it is
  // the largest payload the API serves and every other stage ignores it.
  useEffect(() => {
    if (stage !== "reading" || sourceBlocks.length > 0) return;
    api
      .source(id)
      .then((body) => {
        setSourceBlocks(body.blocks);
        setSourceAvailable(body.available);
        setSourceTruncated(body.truncated);
      })
      .catch(() => {
        // A fetch failure is not the same as "this BRD predates the source pane";
        // telling the reader to re-upload a perfectly good document is bad advice.
        setSourceAvailable(false);
        setSourceError(true);
      });
  }, [stage, id, sourceBlocks.length]);

  useEffect(() => {
    if (stage === "boe" && fullySigned) {
      api
        .listActuals(id)
        .then(setActuals)
        .catch(() => undefined);
    }
  }, [stage, fullySigned, id]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!summary || !state) {
    return <p className="muted">…</p>;
  }

  const blocked = new Set(state.blocked_ids);
  // Same definition the workspace and the board use: unapplied, not un-answered.
  const openQuestions = state.questions.filter(
    (question) => question.status !== "applied",
  );

  const stages: { key: StageKey; label: string }[] = [
    { key: "reading", label: t(locale, "stageReading") },
    { key: "questions", label: t(locale, "stageQuestions") },
    { key: "impact", label: t(locale, "stageImpact") },
    { key: "desk", label: t(locale, "stageEstimate") },
    { key: "boe", label: t(locale, "stageBoe") },
  ];
  const order: StageKey[] = ["reading", "questions", "impact", "desk", "boe"];
  const reached: StageKey = summary.has_boe
    ? fullySigned
      ? "boe"
      : "desk"
    : openQuestions.length > 0
      ? "questions"
      : "impact";
  const done = (key: StageKey) => order.indexOf(key) < order.indexOf(reached);

  const entered = deskItems.filter((item) => item.independent).length;
  // One shared scale across the whole desk, INCLUDING the Delphi panel's bands. The
  // overlay is drawn directly beneath its row so the two can be compared by eye; a
  // scale that omitted the panel would clamp any band wider than the reader's own and
  // render two different bands as the same bar — a silent visual lie, and precisely
  // what the design's "the width of the disagreement is the finding" depends on.
  const maxBand = Math.max(
    1,
    ...deskItems.flatMap((item) => [
      item.ai?.range.pessimistic ?? 0,
      item.independent?.pessimistic ?? 0,
      ...item.delphi.bands.map((band) => band.pessimistic),
    ]),
  );
  const subtotal = deskItems.reduce(
    (acc, item) => {
      const band = item.independent;
      if (!band) return acc;
      return {
        optimistic: acc.optimistic + band.optimistic,
        likely: acc.likely + band.likely,
        pessimistic: acc.pessimistic + band.pessimistic,
      };
    },
    { optimistic: 0, likely: 0, pessimistic: 0 },
  );
  const signedCount = deskItems.filter((item) => item.signed).length;
  const allRevealed =
    deskItems.length > 0 && deskItems.every((item) => item.ai !== null);
  const draftTotal = deskItems.reduce(
    (acc, item) => {
      const band = item.ai?.range;
      if (!band) return acc;
      return {
        optimistic: acc.optimistic + band.optimistic,
        likely: acc.likely + band.likely,
        pessimistic: acc.pessimistic + band.pessimistic,
      };
    },
    { optimistic: 0, likely: 0, pessimistic: 0 },
  );
  const deskTotal = allRevealed ? draftTotal : subtotal;

  return (
    <section className="scr">
      <div className="page-h">
        <Link href="/" className="lbl">
          ← {t(locale, "estimates")}
        </Link>
        <IconEstimates size={18} />
        <h2>{summary.brd_ref}</h2>
        <span className="sub">{summary.title}</span>
      </div>

      <div className="card" style={{ overflow: "hidden", marginBottom: 18 }}>
        <BandHeader
          title={summary.brd_ref}
          subtitle={
            <Lbl>
              {stage === "desk" && !summary.has_boe
                ? t(locale, "stateNoDraft")
                : stage === "desk"
                  ? allRevealed
                    ? t(locale, "stateDraftRevealed")
                    : t(locale, "stateDraftClosed")
                  : summary.title.slice(0, 70)}
            </Lbl>
          }
          center={
            <StageStrip
              stages={stages}
              current={stage}
              done={(key) => done(key as StageKey)}
              onSelect={(key) => setStage(key as StageKey)}
            />
          }
          right={
            <>
              {summary.blocked > 0 && (
                <StatusChip status="crit">
                  {summary.blocked} {t(locale, "blocked")}
                </StatusChip>
              )}
              <Chip>
                {t(locale, "reviewer")}: {estimator || "—"}
              </Chip>
            </>
          }
        />

        {error && (
          <div
            role="alert"
            style={{
              padding: "10px 18px",
              borderBottom: "1px solid var(--line)",
              background: "var(--crit-bg)",
              color: "var(--crit)",
              fontSize: 12.5,
            }}
          >
            {error}
          </div>
        )}

        {/* ---------- 2 · Reading Room ---------- */}
        {stage === "reading" && (
          <ReadingRoom
            locale={locale}
            requirements={state.requirements}
            blockedIds={blocked}
            blocks={sourceBlocks}
            sourceAvailable={sourceAvailable}
            sourceTruncated={sourceTruncated}
            sourceError={sourceError}
            openQuestionCount={openQuestions.length}
            onGoToQuestions={() => setStage("questions")}
          />
        )}

        {/* ---------- 3 · Question Board ---------- */}
        {stage === "questions" && (
          <QuestionBoard
            locale={locale}
            id={id}
            questions={state.questions}
            requirements={state.requirements}
            busy={busy}
            onChanged={refresh}
            onApply={(answers) =>
              run(async () => {
                await api.applyAnswers(id, answers);
                // The server sets boe=None: the draft, its critic findings and every
                // band recorded against it are gone. Leaving deskItems in place left
                // the Estimate Desk rendering a destroyed draft's revealed bands.
                setDeskItems([]);
                setHeld([]);
                setConeStage(null);
                await refresh();
              })
            }
          />
        )}

        {/* ---------- 4 · Impact Map ---------- */}
        {stage === "impact" && (
          <ImpactMap locale={locale} workItems={state.work_items} />
        )}

        {/* ---------- 5 · Estimate Desk ---------- */}
        {stage === "desk" && (
          <>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 18,
                padding: "13px 18px",
                background: "var(--acc-bg)",
                borderBottom: "1px solid var(--acc-line)",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div
                  style={{ fontSize: 14, fontWeight: 600, color: "var(--acc)" }}
                >
                  {t(locale, "independentHeadline")}
                </div>
                <div
                  style={{
                    fontSize: 12.5,
                    color: "var(--ink2)",
                    marginTop: 3,
                    textWrap: "pretty",
                  }}
                >
                  {t(locale, "independentBody")}
                </div>
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  flex: "none",
                }}
              >
                <Mn style={{ color: "var(--ink2)" }}>
                  {entered} / {deskItems.length} {t(locale, "entered")}
                </Mn>
                <input
                  placeholder={t(locale, "estimatorName")}
                  value={estimator}
                  onChange={(event) => setEstimator(event.target.value)}
                  style={{ width: 150 }}
                />
                <button
                  type="button"
                  className="btn"
                  disabled={!estimator || busy}
                  onClick={() => run(loadDesk)}
                >
                  {t(locale, "openDesk")}
                </button>
                {!summary.has_boe && (
                  <button
                    type="button"
                    className="btn p"
                    disabled={busy || summary.status !== "ready_for_estimation"}
                    onClick={() =>
                      run(async () => {
                        const built = await api.buildBoe(id);
                        setCritic(built.critic);
                        await refresh();
                        await loadDesk();
                      })
                    }
                  >
                    {t(locale, "buildBoe")}
                  </button>
                )}
              </div>
            </div>

            {/* The desk carries eleven columns at the design's 1280px minimum, so it
                scrolls in its OWN container: the card clips overflow, which would
                silently amputate Status and Evidence instead of letting the reader
                reach them. */}
            <div style={{ overflowX: "auto" }}>
              <table className="dt" style={{ minWidth: 1180 }}>
                <thead>
                  <tr>
                    <th style={{ width: 20, paddingLeft: 14 }} />
                    <th style={{ width: 240 }}>{t(locale, "lineItem")}</th>
                    <th style={{ width: 78 }}>{t(locale, "reqHeader")}</th>
                    <th style={{ width: 110 }}>{t(locale, "impactShort")}</th>
                    <th style={{ width: 106 }}>
                      {t(locale, "confidenceHeader")}
                    </th>
                    <th style={{ width: 250 }}>{t(locale, "yourRange")}</th>
                    <th style={{ width: 200 }}>{t(locale, "draft")}</th>
                    <th style={{ width: 148 }}>{t(locale, "delta")}</th>
                    <th style={{ width: 60 }}>{t(locale, "arHeader")}</th>
                    <th style={{ width: 108 }}>{t(locale, "statusHeader")}</th>
                    <th>{t(locale, "evidence")}</th>
                  </tr>
                </thead>
                <tbody>
                  {deskItems.length === 0 && (
                    <tr>
                      <td
                        colSpan={11}
                        style={{ color: "var(--mut)", fontSize: 12.5 }}
                      >
                        {t(locale, "deskClosedHint")}
                      </td>
                    </tr>
                  )}
                  {deskItems.map((item) => (
                    <DeskRow
                      key={item.work_item.id}
                      locale={locale}
                      item={item}
                      maxBand={maxBand}
                      busy={busy}
                      onRecord={(band) =>
                        run(async () => {
                          await api.recordIndependent(id, {
                            work_item_id: item.work_item.id,
                            estimator,
                            ...band,
                          });
                          await loadDesk();
                        })
                      }
                      onSign={() =>
                        run(async () => {
                          await api.sign(id, {
                            work_item_id: item.work_item.id,
                            name: estimator,
                            role: "Reviewer",
                          });
                          await loadDesk();
                          await refresh();
                        })
                      }
                    />
                  ))}
                  {/* Blocked requirements, drawn as HELD rows. Omitting them made the
                    desk look complete while a requirement sat unpriced behind an open
                    question — "no line item without evidence" has to be VISIBLE. */}
                  {held.map((entry) => (
                    <tr
                      key={entry.requirement_id}
                      style={{ background: "var(--crit-bg)" }}
                    >
                      <td style={{ paddingLeft: 14 }} />
                      <td style={{ fontSize: 13, color: "var(--ink2)" }}>
                        {entry.text.slice(0, 90)}
                      </td>
                      <td>
                        <Mn style={{ color: "var(--acc)" }}>
                          {entry.requirement_id}
                        </Mn>
                      </td>
                      {/* Each cell sits in the column the design puts it in: the
                          blocked chip under Impact, the reason under Your range, the
                          closed chip under Draft. An even colSpan split would land
                          "closed" under Evidence and swallow Status. */}
                      <td>
                        <StatusChip status="crit">
                          {t(locale, "statusBlocked")}
                        </StatusChip>
                      </td>
                      <td>
                        <Mn style={{ color: "var(--mut)" }}>—</Mn>
                      </td>
                      <td
                        style={{
                          fontSize: 12.5,
                          color: "var(--mut)",
                          textWrap: "pretty",
                        }}
                      >
                        {t(locale, "noEvidenceNoLine")}{" "}
                        {t(locale, "heldHeadline")}
                      </td>
                      <td>
                        <Chip style={{ color: "var(--mut)" }}>
                          {t(locale, "closed")}
                        </Chip>
                      </td>
                      <td colSpan={4} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {deskItems.length > 0 && (
              <div
                style={{
                  position: "sticky",
                  bottom: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 16,
                  padding: "12px 18px",
                  borderTop: "1px solid var(--line2)",
                  background: "var(--surf2)",
                }}
              >
                <div
                  style={{ display: "flex", gap: 20, alignItems: "baseline" }}
                >
                  {/* Before the reveal this is YOUR subtotal over the items you
                      entered; once every item is revealed the estimate of record is
                      the draft total, and saying "your subtotal" then would name the
                      wrong number. */}
                  <Lbl>
                    {(() => {
                      const count = allRevealed ? deskItems.length : entered;
                      // "1 items" reads as a bug to the reader even though it is only
                      // a plural; English needs the singular, Turkish never does.
                      const noun =
                        count === 1
                          ? t(locale, "itemOne")
                          : t(locale, "items").toLowerCase();
                      const label = allRevealed
                        ? t(locale, "total")
                        : t(locale, "subtotal");
                      return `${label} · ${count} ${noun}`;
                    })()}
                  </Lbl>
                  <Num style={{ fontSize: 17, fontWeight: 600 }}>
                    {deskTotal.optimistic} — {deskTotal.pessimistic} pd
                  </Num>
                  <Chip>
                    {t(locale, "likelyShort")} {deskTotal.likely} pd
                  </Chip>
                </div>
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  {coneStage && (
                    <Chip
                      style={{
                        color: "var(--crit)",
                        borderColor: "var(--crit)",
                      }}
                      title={t(locale, "coneNarrows")}
                    >
                      {t(
                        locale,
                        coneStage === "detailed"
                          ? "coneDetailed"
                          : coneStage === "approved_scope"
                            ? "coneApproved"
                            : "coneConcept",
                      )}{" "}
                      · {CONE_MULTIPLIER[coneStage] ?? "—"}
                    </Chip>
                  )}
                  <Mn style={{ color: "var(--mut)" }}>
                    {t(locale, "signatures")} {signedCount} / {deskItems.length}
                  </Mn>
                  <div
                    aria-hidden
                    style={{
                      width: 120,
                      height: 6,
                      borderRadius: 3,
                      background: "var(--surf3)",
                      overflow: "hidden",
                      flex: "none",
                    }}
                  >
                    <div
                      style={{
                        width: `${deskItems.length ? (signedCount / deskItems.length) * 100 : 0}%`,
                        height: "100%",
                        background: "var(--ok)",
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
          </>
        )}

        {/* ---------- 6 · BoE Preview & Signature ---------- */}
        {stage === "boe" && (
          <BoePreview
            locale={locale}
            summary={summary}
            fullySigned={fullySigned}
            critic={critic}
            boeDoc={boeDoc}
            workItems={state.work_items}
            actuals={actuals}
            downloadUrl={api.boeDocxUrl(id)}
            busy={busy}
            onRecordActual={(payload) =>
              run(async () => {
                await api.recordActual(id, payload);
                setActuals(await api.listActuals(id));
              })
            }
          />
        )}
      </div>
    </section>
  );
}

/* ---------------- Impact Map ---------------- */

function ImpactMap({
  locale,
  workItems,
}: {
  locale: Locale;
  workItems: WorkItemShape[];
}) {
  const modules = new Map<string, WorkItemShape[]>();
  for (const item of workItems) {
    for (const module of item.module_tags.length
      ? item.module_tags
      : ["(unmapped)"]) {
      modules.set(module, [...(modules.get(module) ?? []), item]);
    }
  }
  const ordered = [...modules.entries()].sort(
    (a, b) => b[1].length - a[1].length,
  );
  const max = Math.max(1, ...ordered.map(([, items]) => items.length));

  return (
    <div style={{ padding: "14px 18px" }}>
      <Lbl>{t(locale, "impactSubtitle")}</Lbl>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          marginTop: 12,
        }}
      >
        {ordered.map(([module, items]) => (
          <div
            key={module}
            style={{ display: "flex", alignItems: "center", gap: 12 }}
          >
            <div
              style={{
                width: 170,
                flex: "none",
                fontSize: 13,
                color: "var(--ink)",
              }}
            >
              {module}
            </div>
            <div
              style={{
                flex: 1,
                height: 16,
                background: "var(--surf3)",
                borderRadius: 8,
                border: "1px solid var(--line2)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${(items.length / max) * 100}%`,
                  height: "100%",
                  background: "var(--acc-bg)",
                  borderRight: "2px solid var(--acc)",
                }}
              />
            </div>
            <Num style={{ width: 46, flex: "none" }}>{items.length}</Num>
            <div style={{ flex: "none", display: "flex", gap: 5 }}>
              {items.slice(0, 3).map((item) => (
                <Mn key={item.id} style={{ color: "var(--mut)" }}>
                  {item.id}
                </Mn>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- 3 · Question Board ---------------- */

const LANES = [
  { key: "open", label: "laneOpen", empty: "laneEmpty_open" },
  { key: "sent", label: "laneSent", empty: "laneEmpty_sent" },
  { key: "answered", label: "laneAnswered", empty: "laneEmpty_answered" },
  { key: "applied", label: "laneApplied", empty: "laneEmpty_applied" },
] as const;

/** The customer loop as four lanes. It used to be two, because nothing ever advanced
 * a question's status: dispatch was not recorded, so "sent" and "answered" could not
 * be distinguished from "open", and an answer could only be applied in bulk. */
function QuestionBoard({
  locale,
  id,
  questions,
  requirements,
  busy,
  onChanged,
  onApply,
}: {
  locale: Locale;
  id: string;
  questions: Question[];
  requirements: Requirement[];
  busy: boolean;
  onChanged: () => Promise<void>;
  onApply: (answers: Record<string, string>) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [recipient, setRecipient] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answeredBy, setAnsweredBy] = useState("");
  const [letter, setLetter] = useState<QuestionLetter | null>(null);
  const [newFor, setNewFor] = useState(requirements[0]?.id ?? "");
  const [newText, setNewText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const selectedIds = [...selected];

  useEffect(() => {
    if (selectedIds.length === 0) {
      setLetter(null);
      return;
    }
    // Compiled on the SERVER: the preview, the clipboard and any export must be the
    // same text. They used to differ — the panel showed a formal message while
    // "Copy text" produced markdown bullets the customer never saw.
    let current = true;
    api
      .questionLetter(id, selectedIds, locale)
      .then((compiled) => {
        // Two selections in quick succession resolve out of order; without this the
        // preview and the clipboard can hold a letter for a selection that is gone.
        if (current) setLetter(compiled);
      })
      .catch(() => {
        if (current) setLetter(null);
      });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, locale, selected]);

  const [working, setWorking] = useState(false);
  const inFlight = busy || working;

  async function act(action: () => Promise<unknown>) {
    if (working) return;
    setError(null);
    setWorking(true);
    try {
      await action();
      await onChanged();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  }

  const waitedDays = (iso?: string | null) =>
    iso ? Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 86_400_000)) : null;

  return (
    <div>
      {error && (
        <div
          role="alert"
          style={{
            padding: "10px 18px",
            background: "var(--crit-bg)",
            color: "var(--crit)",
            fontSize: 12.5,
          }}
        >
          {error}
        </div>
      )}
      <div style={{ display: "flex" }}>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
          }}
        >
          {LANES.map((lane, laneIndex) => {
            const rows = questions.filter((question) => question.status === lane.key);
            return (
              <div
                key={lane.key}
                style={{
                  borderRight:
                    laneIndex < LANES.length - 1 ? "1px solid var(--line)" : undefined,
                  padding: 12,
                  background: lane.key === "open" ? "var(--surf2)" : undefined,
                  minHeight: 240,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 10,
                  }}
                >
                  <Lbl>{t(locale, lane.label)}</Lbl>
                  <Mn style={{ color: "var(--mut)" }}>{rows.length}</Mn>
                </div>
                {rows.length === 0 && (
                  <div style={{ fontSize: 12, color: "var(--mut)", textWrap: "pretty" }}>
                    {t(locale, lane.empty)}
                  </div>
                )}
                {rows.map((question) => (
                  <div
                    key={question.id}
                    className="card"
                    style={{
                      padding: 11,
                      marginBottom: 9,
                      background: lane.key === "applied" ? "var(--surf2)" : undefined,
                      boxShadow: selected.has(question.id)
                        ? "0 0 0 1px var(--acc) inset"
                        : undefined,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      <Mn style={{ color: "var(--acc)" }}>{question.requirement_id}</Mn>
                      {lane.key === "open" && (
                        <input
                          type="checkbox"
                          aria-label={question.id}
                          checked={selected.has(question.id)}
                          onChange={() => {
                            const next = new Set(selected);
                            if (next.has(question.id)) next.delete(question.id);
                            else next.add(question.id);
                            setSelected(next);
                          }}
                        />
                      )}
                    </div>
                    <div style={{ fontSize: 13, margin: "7px 0", textWrap: "pretty" }}>
                      {question.question}
                    </div>

                    {lane.key === "open" && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          fontSize: 11.5,
                          color: "var(--warn)",
                        }}
                      >
                        <span
                          aria-hidden
                          style={{
                            width: 7,
                            height: 7,
                            background: "var(--warn)",
                            transform: "rotate(45deg)",
                            flex: "none",
                          }}
                        />
                        <span style={{ color: "var(--ink2)", textWrap: "pretty" }}>
                          {question.reason}
                        </span>
                      </div>
                    )}

                    {lane.key === "sent" && (
                      <>
                        <Lbl style={{ textTransform: "none", letterSpacing: 0 }}>
                          {t(locale, "waitingDays").replace(
                            "{n}",
                            String(waitedDays(question.sent_at) ?? 0),
                          )}
                          {question.recipient ? ` · ${question.recipient}` : ""}
                        </Lbl>
                        <div style={{ display: "flex", gap: 5, marginTop: 8 }}>
                          <input
                            style={{ flex: 1, minWidth: 0 }}
                            placeholder={t(locale, "answerFrom")}
                            value={answers[question.id] ?? ""}
                            onChange={(event) =>
                              setAnswers({ ...answers, [question.id]: event.target.value })
                            }
                          />
                        </div>
                        <button
                          type="button"
                          className="btn"
                          style={{ marginTop: 6, width: "100%", justifyContent: "center" }}
                          disabled={inFlight || !(answers[question.id] ?? "").trim() || !answeredBy}
                          onClick={() =>
                            act(() =>
                              api.answerQuestion(
                                id,
                                question.id,
                                answers[question.id],
                                answeredBy,
                              ),
                            )
                          }
                        >
                          {t(locale, "recordAnswer")}
                        </button>
                      </>
                    )}

                    {lane.key === "answered" && (
                      <>
                        <div
                          style={{
                            fontSize: 12.5,
                            background: "var(--ok-bg)",
                            boxShadow: "inset 3px 0 0 var(--ok)",
                            borderRadius: "0 4px 4px 0",
                            padding: "7px 9px",
                            color: "var(--ink)",
                            textWrap: "pretty",
                          }}
                        >
                          “{question.answer}”
                        </div>
                        <Lbl style={{ textTransform: "none", letterSpacing: 0 }}>
                          {question.answered_by}
                          {question.answered_at
                            ? ` · ${new Date(question.answered_at).toLocaleDateString(locale)}`
                            : ""}
                        </Lbl>
                        <button
                          type="button"
                          className="btn"
                          style={{ marginTop: 9, width: "100%", justifyContent: "center" }}
                          disabled={inFlight}
                          onClick={() =>
                            onApply({ [question.id]: question.answer ?? "" })
                          }
                        >
                          {t(locale, "applyToLine")}
                        </button>
                      </>
                    )}

                    {lane.key === "applied" && (
                      <>
                        <div style={{ fontSize: 12, color: "var(--mut)" }}>
                          {t(locale, "appliedTo")}{" "}
                          <Mn style={{ color: "var(--ink2)" }}>
                            {question.applied_to ?? "—"}
                          </Mn>
                        </div>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 7,
                            marginTop: 9,
                            border: "1px solid var(--acc-line)",
                            background: "var(--acc-bg)",
                            color: "var(--acc)",
                            borderRadius: 4,
                            padding: "6px 8px",
                            fontSize: 11.5,
                          }}
                        >
                          <span
                            aria-hidden
                            style={{
                              width: 7,
                              height: 7,
                              borderRadius: "50%",
                              background: "var(--acc)",
                              flex: "none",
                            }}
                          />
                          {t(locale, "reEstimateSuggested")}
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            );
          })}
        </div>

        {/* Customer set */}
        <div
          style={{
            width: 320,
            flex: "none",
            borderLeft: "1px solid var(--line)",
            padding: "14px 16px",
            background: "var(--surf2)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <Lbl>{t(locale, "customerSet")}</Lbl>
            <Chip>
              {selected.size} {t(locale, "selectedShort")}
            </Chip>
          </div>
          <div
            style={{
              fontSize: 12.5,
              color: "var(--ink2)",
              margin: "8px 0 11px",
              textWrap: "pretty",
            }}
          >
            {t(locale, "letterHint")}
          </div>

          {letter ? (
            <div
              className="card doc"
              style={{ padding: "13px 15px", fontSize: 12.5, lineHeight: 1.6, color: "var(--ink2)" }}
            >
              <div style={{ color: "var(--ink)", fontWeight: 600, marginBottom: 7 }}>
                {letter.heading}
              </div>
              {letter.paragraphs.map((paragraph, index) => (
                <p key={index} style={{ margin: "0 0 8px" }}>
                  {paragraph}
                </p>
              ))}
            </div>
          ) : (
            <div className="ph" style={{ padding: "20px 14px" }}>
              {t(locale, "selectToCompose")}
            </div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 11, flexWrap: "wrap" }}>
            <button
              type="button"
              className="btn p"
              disabled={!letter}
              onClick={() => letter && navigator.clipboard.writeText(letter.text)}
            >
              {t(locale, "copyText")}
            </button>
            <input
              style={{ width: 130 }}
              placeholder={t(locale, "recipientPlaceholder")}
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
            />
            <button
              type="button"
              className="btn"
              disabled={inFlight || selected.size === 0 || !recipient.trim()}
              onClick={() =>
                act(async () => {
                  await api.sendQuestions(id, selectedIds, recipient.trim());
                  setSelected(new Set());
                })
              }
            >
              {t(locale, "sendSelected")}
            </button>
          </div>

          <div style={{ marginTop: 16, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
            <Lbl>{t(locale, "answeredBy")}</Lbl>
            <input
              style={{ width: "100%", marginTop: 6 }}
              value={answeredBy}
              onChange={(event) => setAnsweredBy(event.target.value)}
            />
          </div>

          <div style={{ marginTop: 16, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
            <Lbl>{t(locale, "newQuestion")}</Lbl>
            <select
              style={{ width: "100%", marginTop: 6 }}
              value={newFor}
              onChange={(event) => setNewFor(event.target.value)}
            >
              {requirements.map((requirement) => (
                <option key={requirement.id} value={requirement.id}>
                  {requirement.id}
                </option>
              ))}
            </select>
            <input
              style={{ width: "100%", marginTop: 6 }}
              placeholder={t(locale, "questionPlaceholder")}
              value={newText}
              onChange={(event) => setNewText(event.target.value)}
            />
            <button
              type="button"
              className="btn"
              style={{ marginTop: 6, width: "100%", justifyContent: "center" }}
              disabled={inFlight || !newText.trim() || !newFor}
              onClick={() =>
                act(async () => {
                  await api.addQuestion(id, {
                    requirement_id: newFor,
                    question: newText.trim(),
                  });
                  setNewText("");
                })
              }
            >
              {t(locale, "newQuestion")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------- 2 · Reading Room ---------------- */

/** The document beside its structured form. Selecting a row scrolls to and highlights
 * the paragraph it came from; the two panes address each other through `source_ref`,
 * the same string the parser stamps on both. */
function ReadingRoom({
  locale,
  requirements,
  blockedIds,
  blocks,
  sourceAvailable,
  sourceTruncated,
  sourceError,
  openQuestionCount,
  onGoToQuestions,
}: {
  locale: Locale;
  requirements: Requirement[];
  blockedIds: Set<string>;
  blocks: DocBlock[];
  sourceAvailable: boolean;
  sourceTruncated: boolean;
  sourceError: boolean;
  openQuestionCount: number;
  onGoToQuestions: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const selectedRef =
    requirements.find((requirement) => requirement.id === selected)?.source_ref ?? null;

  const paneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectedRef) return;
    const pane = paneRef.current;
    const target = document.getElementById(`src-${cssId(selectedRef)}`);
    if (!pane || !target) return;
    // The pane's OWN scrollTop, computed from the two rects — not scrollIntoView.
    // Two reasons, both observed rather than assumed: `behavior: "smooth"` did
    // nothing at all in one browser context (the row highlighted, the document never
    // moved, and the visible half of the feature made it look like it worked), and
    // scrollIntoView walks ancestors, so it can scroll the PAGE when the pane cannot
    // take it. This moves one element and only that element.
    const delta =
      target.getBoundingClientRect().top -
      pane.getBoundingClientRect().top -
      pane.clientHeight / 2 +
      target.clientHeight / 2;
    pane.scrollTo({ top: pane.scrollTop + delta });
    // `blocks.length` is a dependency on purpose: a row clicked while /source was
    // still in flight would otherwise target an element that did not exist yet and
    // never try again.
  }, [selectedRef, blocks.length]);

  const missingSource =
    selectedRef !== null && blocks.length > 0 && !blocks.some((b) => b.source_ref === selectedRef);

  // Ambiguity heat, by the same rule the rows are coloured with: blocked is critical,
  // any remaining issue is partial, nothing is clear.
  const heat = (requirement: Requirement): "ok" | "warn" | "crit" =>
    blockedIds.has(requirement.id)
      ? "crit"
      : (requirement.ambiguity_issues ?? []).length > 0
        ? "warn"
        : "ok";
  const counts = requirements.reduce(
    (acc, requirement) => ({ ...acc, [heat(requirement)]: acc[heat(requirement)] + 1 }),
    { ok: 0, warn: 0, crit: 0 },
  );

  return (
    <div style={{ display: "flex", height: 560 }}>
      {/* Source pane */}
      <div
        style={{
          width: "47%",
          minWidth: 0,
          borderRight: "1px solid var(--line)",
          background: "var(--surf2)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "8px 14px",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <Lbl>
            {t(locale, "sourcePane")} · {blocks.length}
          </Lbl>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {missingSource && (
              <StatusChip status="warn">{t(locale, "sourceRowMissing")}</StatusChip>
            )}
            {sourceTruncated && (
              <StatusChip status="warn">{t(locale, "sourceTruncated")}</StatusChip>
            )}
          </div>
        </div>
        <div
          ref={paneRef}
          style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "18px 22px" }}
        >
          {!sourceAvailable || blocks.length === 0 ? (
            <div className="ph" style={{ padding: "26px 20px", textWrap: "pretty" }}>
              {sourceError ? t(locale, "sourceFailed") : t(locale, "sourceUnavailable")}
            </div>
          ) : (
            <div
              className="doc"
              style={{
                background: "var(--surf)",
                border: "1px solid var(--line)",
                borderRadius: "var(--r)",
                padding: "24px 28px",
                fontSize: 13.5,
                lineHeight: 1.65,
                color: "var(--ink2)",
              }}
            >
              {blocks.map((block) => (
                <SourceBlock
                  key={block.index}
                  locale={locale}
                  block={block}
                  highlighted={block.source_ref === selectedRef}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Requirements pane */}
      <div style={{ width: "53%", minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 10,
            padding: "8px 14px",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <Lbl>
            {t(locale, "requirementsCount").replace("{n}", String(requirements.length))}
          </Lbl>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <StatusChip status="ok">
              {t(locale, "ambClear")} {counts.ok}
            </StatusChip>
            <StatusChip status="warn">
              {t(locale, "ambPartial")} {counts.warn}
            </StatusChip>
            <StatusChip status="crit">
              {t(locale, "ambAmbiguous")} {counts.crit}
            </StatusChip>
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
          <table className="dt">
            <thead>
              <tr>
                <th style={{ width: 4, padding: 0 }} />
                <th style={{ width: 88 }}>{t(locale, "idHeader")}</th>
                <th>{t(locale, "textHeader")}</th>
                <th style={{ width: 116 }}>{t(locale, "sourceWord")}</th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((requirement) => {
                const status = heat(requirement);
                const isSelected = selected === requirement.id;
                return (
                  <tr
                    key={requirement.id}
                    onClick={() => setSelected(isSelected ? null : requirement.id)}
                    style={{
                      cursor: "pointer",
                      background: isSelected ? "var(--acc-bg)" : undefined,
                      boxShadow: isSelected ? "inset 0 0 0 1px var(--acc-line)" : undefined,
                    }}
                  >
                    <td
                      style={{
                        padding: 0,
                        background:
                          status === "ok"
                            ? "var(--ok)"
                            : status === "warn"
                              ? "var(--warn)"
                              : "var(--crit)",
                      }}
                    />
                    <td>
                      <Mn style={{ color: status === "crit" ? "var(--crit)" : "var(--ink2)" }}>
                        {requirement.id}
                      </Mn>
                    </td>
                    <td>
                      <div style={{ color: "var(--ink2)", textWrap: "pretty" }}>
                        {requirement.text}
                      </div>
                      {/* The WHOLE reason sentence, not the issue slug before the colon:
                          "partial" tells the reader nothing they can act on. */}
                      {(requirement.ambiguity_issues ?? []).map((issue) => (
                        <div
                          key={issue}
                          style={{
                            display: "flex",
                            gap: 7,
                            alignItems: "flex-start",
                            marginTop: 6,
                            fontSize: 12,
                          }}
                        >
                          <span
                            aria-hidden
                            style={{
                              width: 8,
                              height: 8,
                              marginTop: 4,
                              flex: "none",
                              background: status === "crit" ? "var(--crit)" : "var(--warn)",
                              transform: status === "crit" ? undefined : "rotate(45deg)",
                            }}
                          />
                          <span style={{ color: "var(--ink2)", textWrap: "pretty" }}>
                            {issueSentence(locale, issue)}
                          </span>
                        </div>
                      ))}
                      {(requirement.anchors ?? []).map((anchor, index) => (
                        <AnchorPill key={index} locale={locale} snippet={anchor.snippet} />
                      ))}
                    </td>
                    <td>
                      <Mn style={{ color: "var(--mut)" }}>
                        {shortRef(requirement.source_ref)}
                      </Mn>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 14,
            padding: "11px 14px",
            borderTop: "1px solid var(--line)",
            background: "var(--surf2)",
          }}
        >
          <span style={{ fontSize: 12.5, color: "var(--mut)", textWrap: "pretty" }}>
            {t(locale, "selectRowHint")}
          </span>
          {openQuestionCount > 0 && (
            <button type="button" className="btn p" onClick={onGoToQuestions}>
              {t(locale, "sendToBoard").replace("{n}", String(openQuestionCount))}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** A source_ref is free-form text ("block#12 @ 3 > 3.2"); this makes it usable as a
 * DOM id without inventing a parallel identifier on the server. */
function cssId(sourceRef: string): string {
  return sourceRef.replace(/[^A-Za-z0-9_-]/g, "_");
}

/** "block#12 @ 3.2 Kapsam" reads as machinery; the reader wants the heading. */
function shortRef(sourceRef: string | null | undefined): string {
  if (!sourceRef) return "—";
  const trail = sourceRef.split(" @ ")[1];
  if (trail && trail !== "(root)") return trail.split(" > ").slice(-1)[0].slice(0, 28);
  // No heading trail: show the position, not "block#12 @ (root)". The ref is
  // internal addressing and reads as a leak of the implementation.
  const block = sourceRef.match(/block#(\d+)/);
  return block ? `¶${block[1]}` : "—";
}

function AnchorPill({ locale, snippet }: { locale: Locale; snippet: string }) {
  return (
    <span
      title={t(locale, "anchorTooltip")}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        border: "1px dashed var(--crit)",
        background: "var(--crit-bg)",
        borderRadius: 4,
        padding: "2px 7px",
        marginTop: 6,
        marginRight: 6,
        fontFamily: "var(--font-sans)",
        fontSize: 11.5,
        color: "var(--ink2)",
      }}
    >
      <span aria-hidden style={{ width: 8, height: 8, flex: "none", background: "var(--crit)" }} />
      {snippet}
      <Mn style={{ color: "var(--crit)" }}>{t(locale, "quarantined")}</Mn>
    </span>
  );
}

function SourceBlock({
  locale,
  block,
  highlighted,
}: {
  locale: Locale;
  block: DocBlock;
  highlighted: boolean;
}) {
  const mark = highlighted
    ? {
        background: "var(--acc-bg)",
        boxShadow: "inset 3px 0 0 var(--acc)",
        padding: "7px 10px",
        borderRadius: "0 4px 4px 0",
        color: "var(--ink)",
      }
    : {};
  const id = `src-${cssId(block.source_ref)}`;

  if (block.kind === "table") {
    return (
      <div id={id} style={{ margin: "10px 0", ...mark }}>
        <table
          className="dt"
          style={{ fontFamily: "var(--font-sans)", fontSize: 12, tableLayout: "fixed" }}
        >
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    style={{
                      fontWeight: rowIndex === 0 ? 500 : undefined,
                      color: rowIndex === 0 ? "var(--ink)" : "var(--ink2)",
                      textWrap: "pretty",
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <BlockAnchors locale={locale} block={block} />
      </div>
    );
  }
  if (block.kind === "title" || block.kind === "heading") {
    return (
      <div
        id={id}
        style={{
          fontSize: block.kind === "title" ? 16 : 15,
          fontWeight: 600,
          color: "var(--ink)",
          margin: "14px 0 8px",
          ...mark,
        }}
      >
        {block.text}
        <BlockAnchors locale={locale} block={block} />
      </div>
    );
  }
  return (
    <div id={id} style={{ margin: "0 0 10px", ...mark }}>
      {block.kind === "list_item" ? `• ${block.text}` : block.text}
      {block.text_truncated && <Mn style={{ color: "var(--mut)" }}> […]</Mn>}
      <BlockAnchors locale={locale} block={block} />
    </div>
  );
}

function BlockAnchors({ locale, block }: { locale: Locale; block: DocBlock }) {
  if (block.anchors.length === 0) return null;
  return (
    <div>
      {block.anchors.map((anchor, index) => (
        <div key={index}>
          <AnchorPill locale={locale} snippet={anchor.snippet} />
        </div>
      ))}
    </div>
  );
}

/* ---------------- Desk row ---------------- */

function DeskRow({
  locale,
  item,
  maxBand,
  busy,
  onRecord,
  onSign,
}: {
  locale: Locale;
  item: DeskItem;
  maxBand: number;
  busy: boolean;
  onRecord: (band: {
    optimistic: number;
    likely: number;
    pessimistic: number;
    rationale?: string;
  }) => void;
  onSign: () => void;
}) {
  const [o, setO] = useState("");
  const [l, setL] = useState("");
  const [p, setP] = useState("");
  const [rationale, setRationale] = useState("");
  const [expanded, setExpanded] = useState(false);
  const parseBand = (raw: string): number | null => {
    const value = Number(raw.trim().replace(",", "."));
    return Number.isFinite(value) && value >= 0 ? value : null;
  };
  const band = { o: parseBand(o), l: parseBand(l), p: parseBand(p) };
  const valid =
    band.o !== null &&
    band.l !== null &&
    band.p !== null &&
    band.o <= band.l &&
    band.l <= band.p;

  return (
    <>
      <tr
        style={
          item.independent
            ? undefined
            : {
                background: "var(--surf2)",
                boxShadow: "inset 2px 0 0 var(--acc)",
              }
        }
      >
        <td style={{ paddingLeft: 14 }}>
          {item.ai ? (
            // Revealed rows expand into the assumptions/risks panel (design's ▾/▸).
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
              aria-label={`${t(locale, "assumptionsWord")} / ${t(locale, "risksWord")}`}
              style={{
                border: "none",
                background: "none",
                cursor: "pointer",
                padding: 0,
                color: "var(--acc)",
                font: "inherit",
              }}
            >
              <Mn style={{ color: "var(--acc)" }}>{expanded ? "▾" : "▸"}</Mn>
            </button>
          ) : (
            <Mn
              style={{ color: item.independent ? "var(--ok)" : "var(--acc)" }}
            >
              {item.independent ? "✓" : "▸"}
            </Mn>
          )}
        </td>
        <td>
          <div style={{ fontSize: 13, color: "var(--ink)" }}>
            {item.work_item.title}
          </div>
          <Mn style={{ color: "var(--mut)" }}>{item.work_item.id}</Mn>
          {item.discovery_pd !== null && (
            <div style={{ marginTop: 4 }}>
              <Chip
                style={{ color: "var(--crit)", borderColor: "var(--crit)" }}
                title={t(locale, "weakEvidenceBody")}
              >
                {t(locale, "discoveryChip")} {item.discovery_pd} pd
              </Chip>
            </div>
          )}
        </td>
        <td>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {item.work_item.requirement_ids.map((req) => (
              <Mn key={req} style={{ color: "var(--acc)" }}>
                {req}
              </Mn>
            ))}
            {item.work_item.requirement_ids.length === 0 && (
              <Mn style={{ color: "var(--mut)" }}>—</Mn>
            )}
          </div>
        </td>
        <td>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {item.work_item.module_tags.slice(0, 2).map((module) => (
              <Chip key={module}>{module}</Chip>
            ))}
          </div>
        </td>
        <td>
          {/* Confidence travels BEFORE the reveal — a grade, never a band. */}
          {item.confidence ? (
            <StatusChip
              status={
                item.confidence === "high"
                  ? "ok"
                  : item.confidence === "low"
                    ? "crit"
                    : "warn"
              }
            >
              {item.confidence}
            </StatusChip>
          ) : (
            <Mn style={{ color: "var(--mut)" }}>—</Mn>
          )}
        </td>
        <td>
          {item.independent ? (
            <RangeBar
              band={item.independent}
              max={maxBand}
              accent="var(--ok)"
            />
          ) : (
            <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
              <input
                style={{ width: 52 }}
                placeholder="O"
                value={o}
                onChange={(e) => setO(e.target.value)}
              />
              <input
                style={{ width: 52 }}
                placeholder="L"
                value={l}
                onChange={(e) => setL(e.target.value)}
              />
              <input
                style={{ width: 52 }}
                placeholder="P"
                value={p}
                onChange={(e) => setP(e.target.value)}
              />
              <button
                type="button"
                className="btn"
                disabled={busy || !valid}
                onClick={() => {
                  if (!valid) return;
                  onRecord({
                    optimistic: band.o as number,
                    likely: band.l as number,
                    pessimistic: band.p as number,
                    rationale: rationale.trim() || undefined,
                  });
                }}
              >
                {t(locale, "record")}
              </button>
            </div>
          )}
          {!item.independent && (
            <>
              <input
                style={{ width: "100%", marginTop: 5 }}
                placeholder={t(locale, "rationalePlaceholder")}
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
              />
              <div
                style={{ fontSize: 11.5, color: "var(--mut)", marginTop: 4 }}
              >
                {t(locale, "rationaleHint")}
              </div>
            </>
          )}
        </td>
        <td>
          {item.ai ? (
            <RangeBar band={item.ai.range} max={maxBand} />
          ) : (
            // Honest closed state — the design forbids a blurred reveal.
            <Chip style={{ color: "var(--mut)" }}>{t(locale, "closed")}</Chip>
          )}
          {item.delphi.state === "below_threshold" && (
            // Says how far the panel is from opening WITHOUT any band-shaped number:
            // with two panelists a median plus your own band reconstructs the other's.
            <Chip style={{ color: "var(--mut)", marginLeft: 6 }}>
              {t(locale, "delphiBelow")
                .replace("{have}", String(item.delphi.estimators))
                .replace("{need}", String(item.delphi.threshold))}
            </Chip>
          )}
        </td>
        <td>
          {/* DeltaIndicator: the RELATIONSHIP between the two ranges first, the signed
              number second. A lone "+3 pd" is colour-only and reads as a verdict; what
              the reader needs is whether the two bands overlap at all. */}
          {item.delta_likely !== null && item.independent && item.ai ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {item.independent.optimistic <= item.ai.range.pessimistic &&
              item.ai.range.optimistic <= item.independent.pessimistic ? (
                <StatusChip status="ok">
                  {t(locale, "deltaIntersect")}
                </StatusChip>
              ) : (
                <StatusChip status="crit">
                  {t(locale, "deltaDisjoint")}
                </StatusChip>
              )}
              <Num style={{ color: "var(--mut)" }}>
                {item.delta_likely > 0 ? "+" : ""}
                {item.delta_likely} pd
              </Num>
            </div>
          ) : (
            <Mn style={{ color: "var(--mut)" }}>—</Mn>
          )}
        </td>
        <td>
          {item.ai ? (
            <Mn style={{ color: "var(--ink2)" }}>
              {item.ai.assumptions.length} / {item.ai.risks.length}
            </Mn>
          ) : (
            <Mn style={{ color: "var(--mut)" }}>—</Mn>
          )}
        </td>
        <td>
          {item.signed ? (
            <StatusChip status="ok">{t(locale, "signed")}</StatusChip>
          ) : item.ai ? (
            <Chip style={{ color: "var(--ink2)" }}>
              {t(locale, "statusReviewed")}
            </Chip>
          ) : (
            <Chip style={{ color: "var(--mut)" }}>
              {t(locale, "statusDraft")}
            </Chip>
          )}
        </td>
        <td>
          {item.ai ? (
            <div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {/* Aggregated per KIND with counts: listing the first three and
                    dropping the rest hid evidence without saying so. */}
                {Object.entries(
                  item.ai.evidence.reduce<Record<string, number>>(
                    (acc, ref) => {
                      acc[ref.kind] = (acc[ref.kind] ?? 0) + 1;
                      return acc;
                    },
                    {},
                  ),
                ).map(([kind, count]) => (
                  <EvidenceChip key={kind} kind={kind} label={String(count)} />
                ))}
              </div>
              {item.signed ? (
                <StatusChip status="ok">{t(locale, "signed")}</StatusChip>
              ) : (
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  onClick={onSign}
                >
                  {t(locale, "sign")}
                </button>
              )}
            </div>
          ) : (
            <Mn style={{ color: "var(--mut)" }}>—</Mn>
          )}
        </td>
      </tr>
      {expanded && item.ai && (
        <tr style={{ background: "var(--surf2)" }}>
          <td colSpan={11} style={{ padding: "12px 18px 14px 44px" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 20,
              }}
            >
              <div>
                <Lbl>
                  {t(locale, "assumptionsWord")} · {item.ai.assumptions.length}
                </Lbl>
                <ul
                  style={{
                    margin: "7px 0 0",
                    paddingLeft: 16,
                    fontSize: 12.5,
                    color: "var(--ink2)",
                  }}
                >
                  {item.ai.assumptions.map((entry, index) => (
                    <li
                      key={index}
                      style={{ marginBottom: 4, textWrap: "pretty" }}
                    >
                      {entry.text}
                    </li>
                  ))}
                  {item.ai.assumptions.length === 0 && (
                    <li
                      style={{
                        listStyle: "none",
                        marginLeft: -16,
                        color: "var(--mut)",
                      }}
                    >
                      —
                    </li>
                  )}
                </ul>
              </div>
              <div>
                <Lbl>
                  {t(locale, "risksWord")} · {item.ai.risks.length}
                </Lbl>
                <ul
                  style={{
                    margin: "7px 0 0",
                    paddingLeft: 16,
                    fontSize: 12.5,
                    color: "var(--ink2)",
                  }}
                >
                  {item.ai.risks.map((entry, index) => (
                    <li
                      key={index}
                      style={{ marginBottom: 4, textWrap: "pretty" }}
                    >
                      {entry.text}
                      {entry.contingency_pd !== null && (
                        <Chip style={{ marginLeft: 6, color: "var(--warn)" }}>
                          +{entry.contingency_pd} pd
                        </Chip>
                      )}
                    </li>
                  ))}
                  {item.ai.risks.length === 0 && (
                    <li
                      style={{
                        listStyle: "none",
                        marginLeft: -16,
                        color: "var(--mut)",
                      }}
                    >
                      —
                    </li>
                  )}
                </ul>
              </div>
            </div>
            {item.rationale && (
              <div style={{ marginTop: 12, maxWidth: 420 }}>
                <Lbl>{t(locale, "rationaleLabel")}</Lbl>
                <div
                  className="card"
                  style={{
                    padding: "9px 11px",
                    marginTop: 6,
                    fontSize: 12.5,
                    color: "var(--ink2)",
                    textWrap: "pretty",
                  }}
                >
                  “{item.rationale}”
                </div>
              </div>
            )}
            {item.work_item.requirement_ids.length > 0 && (
              <div
                style={{
                  display: "flex",
                  gap: 6,
                  marginTop: 10,
                  alignItems: "center",
                }}
              >
                <Lbl>{t(locale, "reqHeader")}</Lbl>
                {item.work_item.requirement_ids.map((req) => (
                  <Mn key={req} style={{ color: "var(--acc)" }}>
                    {req}
                  </Mn>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
      {/* The panel is a second row spanning the table, exactly as the design draws it:
          it belongs to the item above, not to a column. */}
      {item.delphi.state === "open" && (
        <tr style={{ background: "var(--surf2)" }}>
          <td colSpan={11} style={{ padding: "14px 18px 16px 44px" }}>
            <DelphiOverlay
              bands={item.delphi.bands}
              consensus={item.delphi.consensus}
              max={maxBand}
              label={t(locale, "delphiLabel")}
              caption={t(locale, "delphiCaption")}
            />
            <div
              style={{
                display: "flex",
                gap: 10,
                marginTop: 10,
                paddingLeft: 142,
              }}
            >
              {item.delphi.consensus && (
                <Chip
                  style={{
                    color: "var(--acc)",
                    borderColor: "var(--acc-line)",
                  }}
                >
                  {t(locale, "delphiConsensus")}{" "}
                  {item.delphi.consensus.optimistic}–
                  {item.delphi.consensus.pessimistic}
                </Chip>
              )}
              <Chip>
                {t(locale, "delphiSpread")} {item.delphi.spread_likely}
              </Chip>
              {/* Shape carries the state, not colour alone: intersecting ranges are a
                  circle, a disjoint panel is a diamond that wants a conversation. */}
              <StatusChip
                status={item.delphi.overlap === "intersect" ? "ok" : "warn"}
              >
                {t(
                  locale,
                  item.delphi.overlap === "intersect"
                    ? "delphiIntersect"
                    : "delphiDisjoint",
                )}
              </StatusChip>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/* ---------------- BoE preview & signature ---------------- */

function BoePreview({
  locale,
  summary,
  fullySigned,
  critic,
  boeDoc,
  workItems,
  actuals,
  downloadUrl,
  busy,
  onRecordActual,
}: {
  locale: Locale;
  summary: EstimateSummary;
  fullySigned: boolean;
  critic: string[];
  boeDoc: BoeDocShape | null;
  workItems: WorkItemShape[];
  actuals: ActualEntry[];
  downloadUrl: string;
  busy: boolean;
  onRecordActual: (payload: {
    work_item_id: string;
    actual_effort: number;
    actual_source: string;
    scope_changed: boolean;
    team?: string;
  }) => void;
}) {
  const [effort, setEffort] = useState<Record<string, string>>({});
  const [team, setTeam] = useState<Record<string, string>>({});
  const titleOf = (workItemId: string) =>
    workItems.find((item) => item.id === workItemId)?.title ?? workItemId;

  if (!summary.has_boe) {
    return (
      <div style={{ padding: "26px 18px", color: "var(--mut)", fontSize: 13 }}>
        {t(locale, "noDraftYet")}
      </div>
    );
  }

  const boeLines = boeDoc?.lines ?? [];
  // Register sections merge document-level entries with per-line ones, numbered
  // A-01… / R-01… the way the design's document reads.
  const allAssumptions = [
    ...(boeDoc?.global_assumptions ?? []),
    ...boeLines.flatMap((line) => line.assumptions ?? []),
  ];
  const allRisks = [
    ...(boeDoc?.global_risks ?? []),
    ...boeLines.flatMap((line) => line.risks ?? []),
  ];

  const total = boeLines.reduce(
    (acc, line) => ({
      optimistic: acc.optimistic + line.range.optimistic,
      likely: acc.likely + line.range.likely,
      pessimistic: acc.pessimistic + line.range.pessimistic,
    }),
    { optimistic: 0, likely: 0, pessimistic: 0 },
  );

  return (
    <div style={{ display: "flex" }}>
      <div
        className="doc"
        style={{ flex: 1, minWidth: 0, padding: "16px 20px" }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>
            {t(locale, "boeTitle")} — {summary.brd_ref}
          </span>
          {!fullySigned && (
            <>
              <Chip style={{ color: "var(--warn)" }}>
                {t(locale, "draftWord")}
              </Chip>
              <StatusChip status="warn">
                {t(locale, "pendingSignature")}
              </StatusChip>
            </>
          )}
        </div>
        {/* The design shows the draft document before signing; the API withholds it
            (GET /v1/estimates/{id} returns boe:null until fully_signed) because the
            document carries every line's band and reading it would defeat the
            independent-first gate on the desk. Rendering the sections anyway would
            print an empty document totalling 0 pd — so the honest state stays, and
            closing the gap for real is ROADMAP S12-5 (it needs a per-estimator
            reveal gate on the document, not a frontend change). */}
        {!fullySigned ? (
          <p
            style={{
              fontSize: 13,
              color: "var(--ink2)",
              marginTop: 10,
              textWrap: "pretty",
            }}
          >
            {t(locale, "signAllFirst")}
          </p>
        ) : (
          <>
            <table className="dt" style={{ marginTop: 14 }}>
              <thead>
                <tr>
                  <th>{t(locale, "lineItem")}</th>
                  <th style={{ width: 200 }}>{t(locale, "range")}</th>
                  <th style={{ width: 160 }}>{t(locale, "actualEffort")}</th>
                </tr>
              </thead>
              <tbody>
                {boeLines.map((line) => {
                  const recorded = actuals.find(
                    (a) => a.work_item_id === line.work_item_id,
                  );
                  return (
                    <tr key={line.work_item_id}>
                      <td style={{ fontFamily: "var(--font-sans)" }}>
                        {titleOf(line.work_item_id)}
                        <div>
                          <Mn style={{ color: "var(--mut)" }}>
                            {line.work_item_id}
                          </Mn>
                        </div>
                      </td>
                      <td className="num">
                        {line.range.optimistic} / {line.range.likely} /{" "}
                        {line.range.pessimistic} pd
                      </td>
                      <td style={{ fontFamily: "var(--font-sans)" }}>
                        {recorded ? (
                          <div
                            style={{
                              display: "flex",
                              gap: 6,
                              alignItems: "center",
                            }}
                          >
                            <Num>{recorded.actual_effort} pd</Num>
                            {recorded.scope_changed ? (
                              <StatusChip status="crit">
                                {t(locale, "scopeChanged")}
                              </StatusChip>
                            ) : recorded.deviation !== null ? (
                              <Chip
                                tone={
                                  recorded.deviation > 1.5 ||
                                  recorded.deviation < 0.66
                                    ? "crit"
                                    : "neutral"
                                }
                              >
                                ×{recorded.deviation}
                              </Chip>
                            ) : null}
                          </div>
                        ) : (
                          <div style={{ display: "flex", gap: 5 }}>
                            <input
                              style={{ width: 66 }}
                              placeholder="pd"
                              value={effort[line.work_item_id] ?? ""}
                              onChange={(event) =>
                                setEffort({
                                  ...effort,
                                  [line.work_item_id]: event.target.value,
                                })
                              }
                            />
                            <input
                              style={{ width: 110 }}
                              placeholder={t(locale, "teamPlaceholder")}
                              value={team[line.work_item_id] ?? ""}
                              onChange={(event) =>
                                setTeam({
                                  ...team,
                                  [line.work_item_id]: event.target.value,
                                })
                              }
                            />
                            <button
                              type="button"
                              className="btn"
                              disabled={
                                busy ||
                                parseEffort(effort[line.work_item_id] ?? "") ===
                                  null
                              }
                              onClick={() => {
                                const value = parseEffort(
                                  effort[line.work_item_id] ?? "",
                                );
                                if (value === null) return;
                                onRecordActual({
                                  work_item_id: line.work_item_id,
                                  actual_effort: value,
                                  actual_source: "timesheet",
                                  scope_changed: false,
                                  // Optional, but the only moment anyone knows it:
                                  // a BRD never says which team delivered the work,
                                  // so an unattributed row can never be sliced later.
                                  team:
                                    (team[line.work_item_id] ?? "").trim() ||
                                    undefined,
                                });
                              }}
                            >
                              {t(locale, "save")}
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div
              style={{
                display: "flex",
                gap: 20,
                alignItems: "baseline",
                marginTop: 14,
                fontFamily: "var(--font-sans)",
              }}
            >
              <Lbl>{t(locale, "total")}</Lbl>
              <Num style={{ fontSize: 17, fontWeight: 600 }}>
                {total.optimistic} — {total.pessimistic} pd
              </Num>
              <Chip>
                {t(locale, "likelyShort")} {total.likely} pd
              </Chip>
            </div>

            {/* 3 · Assumption register — on screen, same content the .docx renders. */}
            {allAssumptions.length > 0 && (
              <div style={{ marginTop: 20 }}>
                <div
                  style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}
                >
                  {t(locale, "assumptionRegister")}
                </div>
                <ul
                  style={{
                    margin: "8px 0 0",
                    paddingLeft: 0,
                    listStyle: "none",
                  }}
                >
                  {allAssumptions.map((entry, index) => (
                    <li
                      key={index}
                      style={{
                        display: "flex",
                        gap: 10,
                        fontSize: 13,
                        color: "var(--ink2)",
                        marginBottom: 5,
                        textWrap: "pretty",
                      }}
                    >
                      <Mn style={{ color: "var(--mut)", flex: "none" }}>
                        A-{String(index + 1).padStart(2, "0")}
                      </Mn>
                      {entry.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* 4 · Risks & contingency */}
            {allRisks.length > 0 && (
              <div style={{ marginTop: 18 }}>
                <div
                  style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}
                >
                  {t(locale, "risksContingency")}
                </div>
                <ul
                  style={{
                    margin: "8px 0 0",
                    paddingLeft: 0,
                    listStyle: "none",
                  }}
                >
                  {allRisks.map((entry, index) => (
                    <li
                      key={index}
                      style={{
                        display: "flex",
                        gap: 10,
                        alignItems: "baseline",
                        fontSize: 13,
                        color: "var(--ink2)",
                        marginBottom: 5,
                        textWrap: "pretty",
                      }}
                    >
                      <Mn style={{ color: "var(--mut)", flex: "none" }}>
                        R-{String(index + 1).padStart(2, "0")}
                      </Mn>
                      <span style={{ flex: 1 }}>{entry.text}</span>
                      {entry.contingency_pd != null &&
                        entry.contingency_pd > 0 && (
                          <Chip style={{ color: "var(--warn)", flex: "none" }}>
                            +{entry.contingency_pd} pd ·{" "}
                            {t(locale, "contingencyNote")}
                          </Chip>
                        )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>

      <aside
        style={{
          width: 320,
          flex: "none",
          borderLeft: "1px solid var(--line)",
          padding: "14px 16px",
          background: "var(--surf2)",
        }}
      >
        <Lbl>{t(locale, "exportSection")}</Lbl>
        <div style={{ marginTop: 10 }}>
          {fullySigned ? (
            <a className="btn p" href={downloadUrl}>
              {t(locale, "downloadDocx")}
            </a>
          ) : (
            <StatusChip status="warn">{t(locale, "notSignedYet")}</StatusChip>
          )}
        </div>

        {critic.length > 0 && (
          <div style={{ marginTop: 18 }}>
            <Lbl>{t(locale, "critic")}</Lbl>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 7,
                marginTop: 8,
              }}
            >
              {critic.map((finding) => (
                <div
                  key={finding}
                  style={{ display: "flex", gap: 9, fontSize: 12.5 }}
                >
                  <span style={{ color: "var(--crit)", flex: "none" }}>✕</span>
                  <span style={{ color: "var(--ink2)" }}>{finding}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
