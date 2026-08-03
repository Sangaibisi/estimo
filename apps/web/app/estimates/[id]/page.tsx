"use client";

/** The estimate workspace: five stages from the design system —
 *  2 · Reading Room · 3 · Question Board · 4 · Impact Map · 5 · Estimate Desk ·
 *  6 · BoE Preview & Signature.
 *
 * Design laws honoured here: the desk shows an HONEST CLOSED STATE (never a blurred
 * reveal), status is shape+colour, every quantity is a range (never one number), and
 * exactly one primary action per region. */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  api,
  parseEffort,
  type ActualEntry,
  type DeskItem,
  type EstimateSummary,
} from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";
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
}

interface Requirement {
  id: string;
  text: string;
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

interface BoeLineShape {
  work_item_id: string;
  range: { optimistic: number; likely: number; pessimistic: number };
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
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [estimator, setEstimator] = useState("");
  const [deskItems, setDeskItems] = useState<DeskItem[]>([]);
  const [critic, setCritic] = useState<string[]>([]);
  const [fullySigned, setFullySigned] = useState(false);
  const [boeLines, setBoeLines] = useState<BoeLineShape[]>([]);
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
    setBoeLines(
      ((detail.boe as { lines?: BoeLineShape[] } | null)?.lines ??
        []) as BoeLineShape[],
    );
  }, [id]);

  useEffect(() => {
    refresh().catch((err) => setError(String(err)));
  }, [refresh]);

  const loadDesk = useCallback(async () => {
    if (!estimator) return;
    setDeskItems((await api.desk(id, estimator)).items);
  }, [id, estimator]);

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
  const openQuestions = state.questions.filter(
    (question) => !(question.id in state.answers),
  );
  const answeredQuestions = state.questions.filter(
    (question) => question.id in state.answers,
  );
  const filledAnswers = Object.fromEntries(
    Object.entries(answers).filter(([, value]) => value.trim()),
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
                  ? t(locale, "stateDraftClosed")
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
          <table className="dt">
            <thead>
              <tr>
                <th style={{ width: 92 }}>{t(locale, "idHeader")}</th>
                <th>{t(locale, "textHeader")}</th>
                <th style={{ width: 210 }}>{t(locale, "ambiguity")}</th>
                <th style={{ width: 120 }}>{t(locale, "anchorsShort")}</th>
              </tr>
            </thead>
            <tbody>
              {state.requirements.map((requirement) => {
                const issues = requirement.ambiguity_issues ?? [];
                const isBlocked = blocked.has(requirement.id);
                return (
                  <tr key={requirement.id}>
                    <td>
                      <Mn
                        style={{
                          color: isBlocked ? "var(--crit)" : "var(--ink2)",
                        }}
                      >
                        {requirement.id}
                      </Mn>
                    </td>
                    <td style={{ color: "var(--ink2)" }}>{requirement.text}</td>
                    <td>
                      {issues.length === 0 ? (
                        <StatusChip status="ok">
                          {t(locale, "clear")}
                        </StatusChip>
                      ) : (
                        <div
                          style={{ display: "flex", gap: 6, flexWrap: "wrap" }}
                        >
                          {issues.slice(0, 2).map((issue) => (
                            <StatusChip
                              key={issue}
                              status={isBlocked ? "crit" : "warn"}
                            >
                              {issue.split(":")[0]}
                            </StatusChip>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      {(requirement.anchors ?? []).length > 0 ? (
                        <Chip tone="warn" title={t(locale, "anchors")}>
                          ⚓ {(requirement.anchors ?? []).length}
                        </Chip>
                      ) : (
                        <Mn style={{ color: "var(--mut)" }}>—</Mn>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {/* ---------- 3 · Question Board ---------- */}
        {stage === "questions" && (
          <div style={{ display: "flex" }}>
            <div
              style={{
                flex: 1,
                minWidth: 0,
                display: "grid",
                gridTemplateColumns: "repeat(2, 1fr)",
              }}
            >
              <div
                style={{
                  padding: 12,
                  borderRight: "1px solid var(--line)",
                  background: "var(--surf2)",
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
                  <Lbl>{t(locale, "laneOpen")}</Lbl>
                  <Mn style={{ color: "var(--mut)" }}>
                    {openQuestions.length}
                  </Mn>
                </div>
                {openQuestions.length === 0 && (
                  <p
                    style={{ fontSize: 12.5, color: "var(--ink2)", margin: 0 }}
                  >
                    {t(locale, "emptyQuestions")}
                  </p>
                )}
                {openQuestions.map((question) => (
                  <div
                    key={question.id}
                    className="card"
                    style={{ padding: 11, marginBottom: 9 }}
                  >
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 8 }}
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(question.id)}
                        onChange={(event) => {
                          const next = new Set(selected);
                          if (event.target.checked) next.add(question.id);
                          else next.delete(question.id);
                          setSelected(next);
                        }}
                        style={{ padding: 0 }}
                      />
                      <Mn style={{ color: "var(--acc)" }}>
                        {question.requirement_id}
                      </Mn>
                    </div>
                    <div
                      style={{
                        fontSize: 12.5,
                        marginTop: 6,
                        color: "var(--ink)",
                      }}
                    >
                      {question.question}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        gap: 6,
                        flexWrap: "wrap",
                        marginTop: 7,
                      }}
                    >
                      {question.reason
                        .split(",")
                        .slice(0, 2)
                        .map((reason) => (
                          <StatusChip key={reason} status="warn">
                            {reason.trim().split(":")[0]}
                          </StatusChip>
                        ))}
                    </div>
                    <input
                      style={{ width: "100%", marginTop: 8 }}
                      placeholder={t(locale, "answerPlaceholder")}
                      value={answers[question.id] ?? ""}
                      onChange={(event) =>
                        setAnswers({
                          ...answers,
                          [question.id]: event.target.value,
                        })
                      }
                    />
                  </div>
                ))}
              </div>

              <div style={{ padding: 12 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 10,
                  }}
                >
                  <Lbl>{t(locale, "laneApplied")}</Lbl>
                  <Mn style={{ color: "var(--mut)" }}>
                    {answeredQuestions.length}
                  </Mn>
                </div>
                {answeredQuestions.map((question) => (
                  <div
                    key={question.id}
                    className="card"
                    style={{
                      padding: 11,
                      marginBottom: 9,
                      background: "var(--surf2)",
                    }}
                  >
                    <Mn style={{ color: "var(--mut)" }}>
                      {question.requirement_id}
                    </Mn>
                    <div
                      style={{
                        fontSize: 12.5,
                        marginTop: 5,
                        color: "var(--ink2)",
                      }}
                    >
                      {question.question}
                    </div>
                    <div
                      style={{
                        fontSize: 12.5,
                        marginTop: 7,
                        paddingLeft: 9,
                        borderLeft: "2px solid var(--ok)",
                        color: "var(--ink)",
                      }}
                    >
                      {state.answers[question.id]}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Composer */}
            <div
              style={{
                width: 320,
                flex: "none",
                borderLeft: "1px solid var(--line)",
                padding: "14px 16px",
                background: "var(--surf2)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                }}
              >
                <Lbl>{t(locale, "customerSet")}</Lbl>
                <Chip>
                  {selected.size} {t(locale, "selectedShort")}
                </Chip>
              </div>
              <p
                style={{
                  fontSize: 12.5,
                  color: "var(--ink2)",
                  margin: "8px 0 11px",
                  textWrap: "pretty",
                }}
              >
                {t(locale, "composerHint")}
              </p>
              <div
                className="card doc"
                style={{
                  padding: "13px 15px",
                  fontSize: 12.5,
                  lineHeight: 1.6,
                  color: "var(--ink2)",
                }}
              >
                <div
                  style={{
                    color: "var(--ink)",
                    fontWeight: 600,
                    marginBottom: 7,
                  }}
                >
                  {summary.brd_ref} — {t(locale, "openPoints")}
                </div>
                {state.questions
                  .filter((question) => selected.has(question.id))
                  .map((question) => (
                    <p key={question.id} style={{ margin: "0 0 8px" }}>
                      {question.question}
                    </p>
                  ))}
                {selected.size === 0 && (
                  <p style={{ margin: 0, color: "var(--mut)" }}>
                    {t(locale, "selectToCompose")}
                  </p>
                )}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 11 }}>
                <button
                  type="button"
                  className="btn p"
                  disabled={busy || Object.keys(filledAnswers).length === 0}
                  onClick={() =>
                    run(async () => {
                      await api.applyAnswers(id, filledAnswers);
                      setAnswers({});
                      setSelected(new Set());
                      setDeskItems([]);
                      await refresh();
                    })
                  }
                >
                  {t(locale, "applyAnswers")}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={selected.size === 0}
                  onClick={() =>
                    navigator.clipboard.writeText(
                      state.questions
                        .filter((question) => selected.has(question.id))
                        .map((question) => `- ${question.question}`)
                        .join("\n"),
                    )
                  }
                >
                  {t(locale, "copyText")}
                </button>
              </div>
            </div>
          </div>
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

            <table className="dt">
              <thead>
                <tr>
                  <th style={{ width: 20, paddingLeft: 14 }} />
                  <th style={{ width: 260 }}>{t(locale, "lineItem")}</th>
                  <th style={{ width: 110 }}>{t(locale, "impactShort")}</th>
                  <th style={{ width: 250 }}>{t(locale, "yourRange")}</th>
                  <th style={{ width: 220 }}>{t(locale, "draft")}</th>
                  <th style={{ width: 140 }}>{t(locale, "delta")}</th>
                  <th>{t(locale, "evidence")}</th>
                </tr>
              </thead>
              <tbody>
                {deskItems.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
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
              </tbody>
            </table>

            {deskItems.length > 0 && (
              <div
                style={{
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
                  <Lbl>
                    {t(locale, "subtotal")} · {entered}{" "}
                    {t(locale, "items").toLowerCase()}
                  </Lbl>
                  <Num style={{ fontSize: 17, fontWeight: 600 }}>
                    {subtotal.optimistic} — {subtotal.pessimistic} pd
                  </Num>
                  <Chip>
                    {t(locale, "likelyShort")} {subtotal.likely} pd
                  </Chip>
                </div>
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  <Mn style={{ color: "var(--mut)" }}>
                    {t(locale, "signatures")} {signedCount} / {deskItems.length}
                  </Mn>
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
            boeLines={boeLines}
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
  }) => void;
  onSign: () => void;
}) {
  const [o, setO] = useState("");
  const [l, setL] = useState("");
  const [p, setP] = useState("");
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
          <Mn style={{ color: item.independent ? "var(--ok)" : "var(--acc)" }}>
            {item.independent ? "✓" : "▸"}
          </Mn>
        </td>
        <td>
          <div style={{ fontSize: 13, color: "var(--ink)" }}>
            {item.work_item.title}
          </div>
          <Mn style={{ color: "var(--mut)" }}>{item.work_item.id}</Mn>
        </td>
        <td>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {item.work_item.module_tags.slice(0, 2).map((module) => (
              <Chip key={module}>{module}</Chip>
            ))}
          </div>
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
                  });
                }}
              >
                {t(locale, "record")}
              </button>
            </div>
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
          {item.delta_likely !== null ? (
            <Num
              style={{
                color:
                  Math.abs(item.delta_likely) < 0.5
                    ? "var(--mut)"
                    : item.delta_likely > 0
                      ? "var(--warn)"
                      : "var(--acc)",
              }}
            >
              {item.delta_likely > 0 ? "+" : ""}
              {item.delta_likely} pd
            </Num>
          ) : (
            <Mn style={{ color: "var(--mut)" }}>—</Mn>
          )}
        </td>
        <td>
          {item.ai ? (
            <div>
              <div>
                {item.ai.evidence.slice(0, 3).map((ref) => (
                  <EvidenceChip
                    key={ref.uri}
                    kind={ref.kind}
                    label={ref.label}
                    uri={ref.uri}
                  />
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
      {/* The panel is a second row spanning the table, exactly as the design draws it:
          it belongs to the item above, not to a column. */}
      {item.delphi.state === "open" && (
        <tr style={{ background: "var(--surf2)" }}>
          <td colSpan={7} style={{ padding: "14px 18px 16px 44px" }}>
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
  boeLines,
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
  boeLines: BoeLineShape[];
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
        <div style={{ fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>
          {t(locale, "boeTitle")} — {summary.brd_ref}
        </div>
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
