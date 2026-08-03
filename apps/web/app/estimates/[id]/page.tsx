"use client";

/** Estimate detail: Requirements · Questions · independent-first Estimate Desk · BoE. */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type DeskItem, type EstimateSummary } from "@/lib/api";
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
}

type Tab = "requirements" | "questions" | "desk" | "boe";

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setLocaleState(detectLocale()), []);

  const refresh = useCallback(async () => {
    const detail = await api.getEstimate(id);
    setSummary(detail.summary);
    setState(detail.state as unknown as StateShape);
  }, [id]);

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
                <th>ID</th>
                <th>Text</th>
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
                        blocked
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
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await api.applyAnswers(id, answers);
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
                })
              }
            />
          ))}
        </div>
      )}

      {tab === "boe" && (
        <div className="card">
          {summary.has_boe ? (
            <>
              <p>
                <a href={api.boeDocxUrl(id)}>{t(locale, "downloadDocx")}</a>
              </p>
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
