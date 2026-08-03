"use client";

/** Estimate detail: Requirements · Questions · independent-first Estimate Desk · BoE. */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type ActualEntry, type DeskItem, type EstimateSummary } from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";
import { RangeBar } from "@/components/RangeBar";
import { EvidenceChip } from "@/components/EvidenceChip";

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

interface StateShape {
  requirements: Requirement[];
  questions: Question[];
  answers: Record<string, string>;
  blocked_ids: string[];
  work_items: { id: string; title: string }[];
}

type Tab = "requirements" | "questions" | "desk" | "boe" | "actuals";

interface BoeLineShape {
  work_item_id: string;
  range: { optimistic: number; likely: number; pessimistic: number };
}

export default function EstimateDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [locale, setLocaleState] = useState<Locale>("en");
  const [summary, setSummary] = useState<EstimateSummary | null>(null);
  const [state, setState] = useState<StateShape | null>(null);
  const [tab, setTab] = useState<Tab>("requirements");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [estimator, setEstimator] = useState("");
  const [deskItems, setDeskItems] = useState<DeskItem[]>([]);
  const [critic, setCritic] = useState<string[]>([]);
  const [fullySigned, setFullySigned] = useState(false);
  const [actuals, setActuals] = useState<ActualEntry[]>([]);
  const [boeLines, setBoeLines] = useState<BoeLineShape[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setLocaleState(detectLocale()), []);

  const refresh = useCallback(async () => {
    const detail = await api.getEstimate(id);
    setSummary(detail.summary);
    setState(detail.state as unknown as StateShape);
    setCritic(detail.critic);
    setFullySigned(detail.fully_signed);
    setBoeLines(((detail.boe as { lines?: BoeLineShape[] } | null)?.lines ?? []) as BoeLineShape[]);
  }, [id]);

  useEffect(() => {
    if (tab === "actuals") {
      api.listActuals(id).then(setActuals).catch((err) => setError(String(err)));
    }
  }, [tab, id]);

  useEffect(() => {
    refresh().catch((err) => setError(String(err)));
  }, [refresh]);

  const loadDesk = useCallback(async () => {
    if (!estimator) return;
    const desk = await api.desk(id, estimator);
    setDeskItems(desk.items);
  }, [id, estimator]);

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
  const openQuestions = state.questions.filter((q) => !(q.id in state.answers));
  // An empty answer is "no answer" — submitting it would silently close the question.
  const filledAnswers = Object.fromEntries(
    Object.entries(answers).filter(([, value]) => value.trim()),
  );
  const maxBand = Math.max(
    1,
    ...deskItems.flatMap((item) => [
      item.ai?.range.pessimistic ?? 0,
      item.independent?.pessimistic ?? 0,
    ]),
  );

  return (
    <main>
      <p>
        <Link href="/">← {t(locale, "estimates")}</Link>
      </p>
      <h1 style={{ marginBottom: 0 }}>{summary.brd_ref}</h1>
      <p className="muted">{summary.title}</p>

      <nav style={{ display: "flex", gap: 8, margin: "16px 0" }}>
        {(
          [
            ["requirements", t(locale, "requirementsTab")],
            ["questions", `${t(locale, "questionsTab")} (${openQuestions.length})`],
            ["desk", t(locale, "deskTab")],
            ["boe", t(locale, "boeTab")],
            ...(fullySigned ? [["actuals", t(locale, "actualsTab")] as [Tab, string]] : []),
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? "primary" : undefined}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      {error && (
        <p style={{ color: "var(--crit)" }} role="alert">
          {error}
        </p>
      )}

      {tab === "requirements" && (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>{t(locale, "idHeader")}</th>
                <th>{t(locale, "textHeader")}</th>
                <th>{t(locale, "ambiguity")}</th>
              </tr>
            </thead>
            <tbody>
              {state.requirements.map((requirement) => (
                <tr key={requirement.id}>
                  <td>
                    {requirement.id}
                    {blocked.has(requirement.id) && (
                      <span className="chip" style={{ color: "var(--crit)", marginLeft: 6 }}>
                        {t(locale, "blocked")}
                      </span>
                    )}
                  </td>
                  <td>{requirement.text}</td>
                  <td>{requirement.ambiguity_score?.toFixed(2) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {state.requirements.some((r) => (r.anchors?.length ?? 0) > 0) && (
            <p className="muted" style={{ marginTop: 12 }}>
              ⚓ {t(locale, "anchors")}
            </p>
          )}
        </div>
      )}

      {tab === "questions" && (
        <div className="card">
          {openQuestions.length === 0 && <p className="muted">✓</p>}
          {openQuestions.map((question) => (
            <div key={question.id} style={{ marginBottom: 12 }}>
              <strong>{question.id}</strong>{" "}
              <span className="chip">{question.requirement_id}</span>
              <p style={{ margin: "4px 0" }}>{question.question}</p>
              <p className="muted" style={{ margin: "2px 0", fontSize: 12 }}>
                {question.reason}
              </p>
              <input
                style={{ width: "100%" }}
                placeholder={t(locale, "answerPlaceholder")}
                value={answers[question.id] ?? ""}
                onChange={(event) =>
                  setAnswers({ ...answers, [question.id]: event.target.value })
                }
              />
            </div>
          ))}
          {openQuestions.length > 0 && (
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="primary"
                disabled={busy || Object.keys(filledAnswers).length === 0}
                onClick={() =>
                  run(async () => {
                    await api.applyAnswers(id, filledAnswers);
                    setAnswers({});
                    setDeskItems([]); // scope may have changed; desk reloads on demand
                    await refresh();
                  })
                }
              >
                {t(locale, "applyAnswers")}
              </button>
              <button
                onClick={() =>
                  navigator.clipboard.writeText(
                    openQuestions.map((q) => `- ${q.question}`).join("\n"),
                  )
                }
              >
                {t(locale, "copyQuestions")}
              </button>
            </div>
          )}
        </div>
      )}

      {tab === "desk" && (
        <div className="card">
          <p className="muted">{t(locale, "independentHint")}</p>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <input
              placeholder={t(locale, "estimatorName")}
              value={estimator}
              onChange={(event) => setEstimator(event.target.value)}
            />
            <button disabled={!estimator || busy} onClick={() => run(loadDesk)}>
              →
            </button>
            {!summary.has_boe && (
              <button
                className="primary"
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
                  await refresh(); // the last signature unlocks the BoE export
                })
              }
            />
          ))}
        </div>
      )}

      {tab === "actuals" && (
        <div className="card">
          <p className="muted">{t(locale, "actualsHint")}</p>
          {boeLines.map((line) => {
            const item = state.work_items.find((wi) => wi.id === line.work_item_id);
            const existing = actuals.find((a) => a.work_item_id === line.work_item_id);
            return (
              <ActualRow
                key={line.work_item_id}
                locale={locale}
                title={item?.title ?? line.work_item_id}
                line={line}
                existing={existing}
                busy={busy}
                onSave={(actual) =>
                  run(async () => {
                    await api.recordActual(id, {
                      work_item_id: line.work_item_id,
                      ...actual,
                    });
                    setActuals(await api.listActuals(id));
                  })
                }
              />
            );
          })}
        </div>
      )}

      {tab === "boe" && (
        <div className="card">
          {summary.has_boe ? (
            <>
              {fullySigned ? (
                <p>
                  <a href={api.boeDocxUrl(id)}>{t(locale, "downloadDocx")}</a>
                </p>
              ) : (
                <p className="muted">{t(locale, "signAllFirst")}</p>
              )}
              {critic.length > 0 && (
                <>
                  <h3>{t(locale, "critic")}</h3>
                  {critic.map((finding) => (
                    <p key={finding} style={{ color: "var(--crit)" }}>
                      {finding}
                    </p>
                  ))}
                </>
              )}
            </>
          ) : (
            <p className="muted">—</p>
          )}
        </div>
      )}
    </main>
  );
}

function ActualRow({
  locale,
  title,
  line,
  existing,
  busy,
  onSave,
}: {
  locale: Locale;
  title: string;
  line: BoeLineShape;
  existing?: ActualEntry;
  busy: boolean;
  onSave: (actual: {
    actual_effort: number;
    actual_source: string;
    scope_changed: boolean;
  }) => void;
}) {
  const [effort, setEffort] = useState("");
  const [source, setSource] = useState("timesheet");
  const [scopeChanged, setScopeChanged] = useState(false);

  return (
    <div style={{ borderTop: "1px solid var(--line)", padding: "12px 0" }}>
      <strong>{title}</strong>{" "}
      <span className="muted">
        {line.range.optimistic} / {line.range.likely} / {line.range.pessimistic} pd
      </span>
      {existing ? (
        <p style={{ margin: "6px 0 0" }}>
          {existing.actual_effort} pd{" "}
          <span className="chip">{existing.actual_source}</span>{" "}
          {existing.scope_changed && (
            <span className="chip" style={{ color: "var(--crit)" }}>
              {t(locale, "scopeChanged")}
            </span>
          )}
          {existing.deviation !== null && !existing.scope_changed && (
            <span className="muted" style={{ marginLeft: 8 }}>
              ×{existing.deviation} {t(locale, "deviationLabel")}
            </span>
          )}
        </p>
      ) : (
        <div style={{ display: "flex", gap: 8, marginTop: 6, alignItems: "center" }}>
          <input
            style={{ width: 90 }}
            placeholder={t(locale, "actualEffort")}
            value={effort}
            onChange={(event) => setEffort(event.target.value)}
          />
          <select
            aria-label={t(locale, "actualSource")}
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            <option value="timesheet">timesheet</option>
            <option value="project-report">project-report</option>
            <option value="expert-recall">expert-recall</option>
          </select>
          <label className="muted" style={{ fontSize: 12 }}>
            <input
              type="checkbox"
              checked={scopeChanged}
              onChange={(event) => setScopeChanged(event.target.checked)}
            />{" "}
            {t(locale, "scopeChanged")}
          </label>
          <button
            disabled={busy || !effort || Number(effort) <= 0}
            onClick={() =>
              onSave({
                actual_effort: Number(effort),
                actual_source: source,
                scope_changed: scopeChanged,
              })
            }
          >
            {t(locale, "save")}
          </button>
        </div>
      )}
    </div>
  );
}


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
  onRecord: (band: { optimistic: number; likely: number; pessimistic: number }) => void;
  onSign: () => void;
}) {
  const [o, setO] = useState("");
  const [l, setL] = useState("");
  const [p, setP] = useState("");

  return (
    <div style={{ borderTop: "1px solid var(--line)", padding: "12px 0" }}>
      <strong>{item.work_item.title}</strong>{" "}
      {item.work_item.module_tags.map((module) => (
        <span key={module} className="chip" style={{ marginLeft: 4 }}>
          {module}
        </span>
      ))}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 8 }}>
        <div>
          <div className="muted" style={{ fontSize: 12 }}>
            {t(locale, "yourBand")}
          </div>
          {item.independent ? (
            <RangeBar band={item.independent} max={maxBand} color="var(--ok)" />
          ) : (
            <div style={{ display: "flex", gap: 4 }}>
              <input style={{ width: 56 }} placeholder="O" value={o} onChange={(e) => setO(e.target.value)} />
              <input style={{ width: 56 }} placeholder="L" value={l} onChange={(e) => setL(e.target.value)} />
              <input style={{ width: 56 }} placeholder="P" value={p} onChange={(e) => setP(e.target.value)} />
              <button
                disabled={busy || !o || !l || !p}
                onClick={() =>
                  onRecord({
                    optimistic: Number(o),
                    likely: Number(l),
                    pessimistic: Number(p),
                  })
                }
              >
                {t(locale, "record")}
              </button>
            </div>
          )}
        </div>
        <div>
          <div className="muted" style={{ fontSize: 12 }}>
            {t(locale, "aiBand")}
            {item.delta_likely !== null && (
              <span style={{ marginLeft: 8 }}>
                {t(locale, "delta")}: {item.delta_likely > 0 ? "+" : ""}
                {item.delta_likely} pd
              </span>
            )}
          </div>
          {item.ai ? (
            <>
              <RangeBar band={item.ai.range} max={maxBand} />
              <div style={{ marginTop: 4 }}>
                {item.ai.evidence.slice(0, 4).map((ref) => (
                  <EvidenceChip key={ref.uri} {...ref} />
                ))}
              </div>
              {item.signed ? (
                <span className="chip" style={{ color: "var(--ok)" }}>
                  ✓ {t(locale, "signed")}
                </span>
              ) : (
                <button disabled={busy} onClick={onSign} style={{ marginTop: 4 }}>
                  {t(locale, "sign")}
                </button>
              )}
            </>
          ) : (
            <div
              className="muted"
              style={{
                border: "1px dashed var(--line)",
                borderRadius: "var(--r)",
                padding: 12,
                textAlign: "center",
              }}
            >
              🔒
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
