"use client";

/** 8 · Calibration Dashboard — "Are our ranges honest? The product grades itself."
 *
 * Design rules honoured: every rate ships with its sample count, the naive baseline
 * sits beside the product's own number (PRINCIPLES #7), and the copy states the
 * result against its target even when the product is losing. */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type MetricsOverview } from "@/lib/api";
import { DATE_LOCALE, t } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, Num, StatusChip } from "@/components/ui";
import { IconCalibration } from "@/components/icons";

export default function CalibrationPage() {
  const [data, setData] = useState<MetricsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [team, setTeam] = useState("");
  const [domain, setDomain] = useState("");
  const [discipline, setDiscipline] = useState("");
  const [months, setMonths] = useState<number | null>(null);
  // Same sequencing rule as the ledger: a slow first response must not land on top of
  // a newer one and leave figures that describe a view nobody is looking at.
  const request = useRef(0);

  const load = useCallback(
    (view: {
      team: string;
      domain: string;
      discipline: string;
      months: number | null;
    }) => {
      const ticket = ++request.current;
      api
        .metrics(view)
        .then((result) => {
          if (ticket !== request.current) return;
          setData(result);
          setError(null);
        })
        .catch((err) => {
          if (ticket !== request.current) return;
          setData(null);
          setError(String(err));
        });
    },
    [],
  );

  useEffect(() => {
    load({ team: "", domain: "", discipline: "", months: null });
  }, [load]);

  if (error) {
    return (
      <section className="scr">
        <div
          role="alert"
          className="card"
          style={{ padding: 16, color: "var(--crit)" }}
        >
          {error}
        </div>
      </section>
    );
  }
  if (!data) return <p className="muted">…</p>;

  const {
    calibration,
    product_accuracy,
    anchoring,
    workflow,
    slices,
    question_impact,
  } = data;
  const pct = (value: number | null) =>
    value === null ? "—" : `${Math.round(value * 100)}%`;
  const coverageOnTarget =
    product_accuracy.coverage !== null &&
    product_accuracy.coverage >= product_accuracy.nominal - 0.05;

  return (
    <section className="scr">
      <div className="page-h">
        <IconCalibration size={18} />
        <h2>{t("calibration")}</h2>
        <span className="sub">{t("calibrationSubtitle")}</span>
      </div>

      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title={t("howHonest")}
          subtitle={
            product_accuracy.samples === 0
              ? t("noData")
              : `${product_accuracy.samples} ${t("completedItems")}`
          }
          right={
            <>
              {product_accuracy.coverage !== null ? (
                <StatusChip status={coverageOnTarget ? "ok" : "warn"}>
                  {t("coverageVsTarget")
                    .replace("{actual}", pct(product_accuracy.coverage))
                    .replace("{target}", pct(product_accuracy.nominal))}
                </StatusChip>
              ) : product_accuracy.samples > 0 ? (
                // Withheld, not missing. "No completed items yet" next to a subtitle
                // reading "2 completed items" is the screen contradicting itself.
                <Chip>
                  {t("sliceWithheld")
                    .replace("{n}", String(product_accuracy.samples))
                    .replace("{need}", String(product_accuracy.min_samples))}
                </Chip>
              ) : (
                <Chip>{t("noCoverageYet")}</Chip>
              )}
              <select
                aria-label={t("teamWord")}
                value={team}
                onChange={(event) => {
                  setTeam(event.target.value);
                  load({ team: event.target.value, domain, discipline, months });
                }}
              >
                <option value="">{t("allTeams")}</option>
                {slices.teams.map((slice) => (
                  <option key={slice.key} value={slice.key}>
                    {slice.key}
                  </option>
                ))}
              </select>
              <select
                aria-label={t("domainWord")}
                value={domain}
                onChange={(event) => {
                  setDomain(event.target.value);
                  load({ team, domain: event.target.value, discipline, months });
                }}
              >
                <option value="">{t("allDomains")}</option>
                {slices.domains.map((slice) => (
                  <option key={slice.key} value={slice.key}>
                    {slice.key}
                  </option>
                ))}
              </select>
              <select
                aria-label={t("disciplineWord")}
                value={discipline}
                onChange={(event) => {
                  setDiscipline(event.target.value);
                  load({ team, domain, discipline: event.target.value, months });
                }}
              >
                <option value="">{t("allDisciplines")}</option>
                {(slices.disciplines ?? []).map((slice) => (
                  <option key={slice.key} value={slice.key}>
                    {slice.key === "frontend"
                      ? t("frontendWord")
                      : slice.key === "backend"
                        ? t("backendWord")
                        : slice.key}
                  </option>
                ))}
              </select>
              <select
                aria-label={t("windowAll")}
                value={months ?? ""}
                onChange={(event) => {
                  const next = event.target.value
                    ? Number(event.target.value)
                    : null;
                  setMonths(next);
                  load({ team, domain, discipline, months: next });
                }}
              >
                <option value="">{t("windowAll")}</option>
                {[12, 24].map((n) => (
                  <option key={n} value={n}>
                    {t("windowMonths").replace("{n}", String(n))}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn"
                onClick={() => exportFigures(data)}
              >
                {t("exportFigures")}
              </button>
            </>
          }
        />

        <div style={{ display: "flex" }}>
          <div
            style={{
              flex: 1,
              minWidth: 0,
              padding: "14px 18px",
              borderRight: "1px solid var(--line)",
            }}
          >
            <Lbl>{t("coverageChartTitle")}</Lbl>
            <div
              style={{
                fontSize: 12,
                color: "var(--mut)",
                margin: "4px 0 10px",
              }}
            >
              {t("coverageChartHint")}
            </div>
            <CoverageChart series={calibration.series} />
            {calibration.current.samples < 100 && (
              <div
                style={{
                  fontSize: 12,
                  color: "var(--ink2)",
                  marginTop: 8,
                  textWrap: "pretty",
                }}
              >
                {t("lowSampleNote")}
              </div>
            )}
          </div>

          <div style={{ width: 420, flex: "none", padding: "14px 18px" }}>
            <Lbl>{t("maeChartTitle")}</Lbl>
            <div
              style={{
                fontSize: 12,
                color: "var(--mut)",
                margin: "4px 0 10px",
              }}
            >
              {t("maeChartHint")}
            </div>
            <MaeBars
              product={product_accuracy.mae_product}
              naive={product_accuracy.mae_naive_median}
            />

            {product_accuracy.mape_product !== null && (
              <div style={{ marginTop: 12 }}>
                <Lbl>{t("mapeTitle")}</Lbl>
                <div style={{ fontSize: 12.5, marginTop: 4 }}>
                  {pct(product_accuracy.mape_product)}{" "}
                  <span style={{ color: "var(--mut)" }}>
                    · {pct(product_accuracy.mape_naive_median)}{" "}
                    {t("naiveMedian")}
                  </span>
                </div>
                {product_accuracy.mape_excluded > 0 && (
                  <div
                    style={{
                      fontSize: 11.5,
                      color: "var(--ink2)",
                      marginTop: 4,
                    }}
                  >
                    {t("mapeExcluded").replace(
                      "{n}",
                      String(product_accuracy.mape_excluded),
                    )}
                  </div>
                )}
              </div>
            )}

            {/* The design's "on this dataset the difference is not meaningful" — a
                claim about a test, so the test's numbers travel with it. */}
            <div
              style={{
                fontSize: 12,
                color: "var(--ink2)",
                marginTop: 10,
                textWrap: "pretty",
              }}
            >
              {verdictSentence(product_accuracy.comparison)}
            </div>

            <div style={{ marginTop: 18 }}>
              <Lbl>{t("transferQuantiles")}</Lbl>
              <table className="dt" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>q10</th>
                    <th>q50</th>
                    <th>q90</th>
                    <th style={{ width: 60 }}>{t("samplesShort")}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="num">
                      {calibration.current.q10.toFixed(2)}
                    </td>
                    <td className="num">
                      {calibration.current.q50.toFixed(2)}
                    </td>
                    <td className="num">
                      {calibration.current.q90.toFixed(2)}
                    </td>
                    <td className="num">{calibration.current.samples}</td>
                  </tr>
                </tbody>
              </table>
              {calibration.current.prior_based && (
                <div style={{ marginTop: 8 }}>
                  <StatusChip status="warn">
                    {t("priorBased")}
                  </StatusChip>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <BandHeader
          title={t("anchoringSection")}
          subtitle={t("anchoringSubtitle")}
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <Tile
            label={t("entryBlind")}
            value={String(anchoring.entry.blind)}
          />
          <Tile
            label={t("entryAfterReadable")}
            value={String(anchoring.entry.after_readable)}
            hint={t("entryHint")}
          />
          <Tile
            label={t("entryUnknown")}
            value={String(anchoring.entry.unknown)}
            last
          />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)" }}>
          <Tile
            label={`${t("anchoringTile")} · ${t("samplesShort")}=${anchoring.samples}`}
            value={
              anchoring.mean_abs_delta === null
                ? "—"
                : `${anchoring.mean_abs_delta} pd`
            }
          />
          <Tile
            label={t("zeroDeltaTile")}
            value={pct(anchoring.zero_delta_share)}
            hint={t("zeroDeltaHint")}
          />
          <Tile label={t("wipTile")} value={String(workflow.wip)} />
          <Tile
            label={t("revisionTile")}
            value={pct(workflow.question_revision_rate)}
          />
          <Tile
            label={t("rebuildTile")}
            value={pct(workflow.rebuild_share)}
            last
          />
        </div>
      </div>

      <SliceBars slices={slices} />
      <QuestionImpact impact={question_impact} />
    </section>
  );
}

/** The design's per-slice bars, with the rule that decides whether a bar exists.
 *
 * A slice below the sample floor is NOT drawn at 0% or 100% — those are the only two
 * values a two-job slice can take, and neither says anything about the team. It is
 * listed with its count and the reason, which is the same self-critical register the
 * coverage headline already uses. */
function SliceBars({
  slices,
}: {
  slices: MetricsOverview["slices"];
}) {
  const all = [...slices.teams, ...slices.domains, ...(slices.disciplines ?? [])];
  const drawable = all.filter((slice) => slice.coverage !== null);
  const worst = drawable.reduce<(typeof drawable)[number] | null>(
    (lowest, slice) =>
      lowest === null ||
      (slice.coverage as number) < (lowest.coverage as number)
        ? slice
        : lowest,
    null,
  );

  return (
    <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
      <BandHeader
        title={t("perSliceTitle")}
        subtitle={t("perSliceHint")}
      />
      {all.length === 0 ? (
        <div
          style={{
            padding: "18px",
            fontSize: 12.5,
            color: "var(--ink2)",
            textWrap: "pretty",
          }}
        >
          {t("noSlicesYet")}
        </div>
      ) : (
        <div style={{ padding: "14px 18px" }}>
          {all.map((slice) => (
            <div
              key={`${slice.kind}:${slice.key}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "6px 0",
              }}
            >
              <span style={{ width: 170, fontSize: 12.5 }} className="mn">
                {slice.key}{" "}
                <span style={{ color: "var(--mut)" }}>
                  {t(slice.kind === "team"
                      ? "teamWord"
                      : slice.kind === "discipline"
                        ? "disciplineWord"
                        : "domainWord",
                  )}
                </span>
              </span>
              <div
                style={{
                  flex: 1,
                  height: 8,
                  borderRadius: 4,
                  background: "var(--surf2)",
                  overflow: "hidden",
                }}
              >
                {slice.coverage !== null && (
                  <div
                    style={{
                      width: `${Math.round(slice.coverage * 100)}%`,
                      height: "100%",
                      borderRadius: 4,
                      background: "var(--acc)",
                    }}
                  />
                )}
              </div>
              <span style={{ width: 200, fontSize: 12, color: "var(--ink2)" }}>
                {slice.coverage !== null
                  ? `${Math.round(slice.coverage * 100)}% · ${slice.samples}`
                  : t("sliceWithheld")
                      .replace("{n}", String(slice.samples))
                      .replace("{need}", String(slices.min_samples))}
              </span>
            </div>
          ))}
          {/* Stated as an observation with its sample count, not as a diagnosis:
              "its ranges are too narrow" is a causal claim, and a coverage rate on
              its own cannot distinguish narrow ranges from a hard quarter. */}
          {worst && (worst.coverage as number) < 0.8 && (
            <div
              style={{
                fontSize: 12.5,
                color: "var(--ink2)",
                marginTop: 10,
                textWrap: "pretty",
              }}
            >
              {t("worstSlice")
                .replace("{key}", worst.key)
                .replace(
                  "{value}",
                  `${Math.round((worst.coverage as number) * 100)}%`,
                )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Did answering a question actually move a line?
 *
 * The empty state is the interesting one: the gate refuses to build a draft over an
 * open question, so most answers arrive BEFORE any draft exists and there is no
 * before-image to diff. That is a fact about the product's own design, and saying it
 * is more useful than a rate computed from three rows. */
function QuestionImpact({
  impact,
}: {
  impact: MetricsOverview["question_impact"];
}) {
  const pct = (value: number | null) =>
    value === null ? "—" : `${Math.round(value * 100)}%`;
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <BandHeader
        title={t("questionImpactTitle")}
        subtitle={t("questionImpactHint")}
      />
      {impact.samples === 0 ? (
        <div
          style={{
            padding: "18px",
            fontSize: 12.5,
            color: "var(--ink2)",
            textWrap: "pretty",
          }}
        >
          {t("questionImpactEmpty")}
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)" }}>
          <Tile
            label={`${t("changedShare")} · ${t("samplesShort")}=${impact.samples}`}
            value={pct(impact.changed_share)}
          />
          <Tile
            label={t("widthChange")}
            value={
              impact.median_width_change === null
                ? "—"
                : `${impact.median_width_change > 0 ? "+" : ""}${Math.round(
                    impact.median_width_change * 100,
                  )}%`
            }
            hint={
              impact.lines_created > 0
                ? t("linesCreated").replace(
                    "{n}",
                    String(impact.lines_created),
                  )
                : undefined
            }
            last
          />
        </div>
      )}
      {impact.reasons.length > 0 && (
        <div
          style={{ padding: "14px 18px", borderTop: "1px solid var(--line)" }}
        >
          <Lbl>{t("reasonsTitle")}</Lbl>
          <div
            style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}
          >
            {impact.reasons.map((reason) => (
              <Chip key={reason.code}>
                {reason.code} · {reason.count}
                {reason.share !== null &&
                  ` (${Math.round(reason.share * 100)}%)`}
              </Chip>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** The comparison verdict as a sentence, with the test's own numbers in it. */
function verdictSentence(
  comparison: MetricsOverview["product_accuracy"]["comparison"],
): string {
  const decided = comparison.wins + comparison.losses;
  const fill = (key: Parameters<typeof t>[0]) =>
    t(key)
      .replace("{wins}", String(comparison.wins))
      .replace("{losses}", String(comparison.losses))
      .replace("{decided}", String(decided))
      .replace(
        "{p}",
        comparison.p_value === null ? "—" : String(comparison.p_value),
      );
  if (comparison.verdict === "no-signal") return t("verdictNoSignal");
  if (comparison.verdict === "pipeline-better")
    return fill("verdictPipelineBetter");
  if (comparison.verdict === "baseline-better")
    return fill("verdictBaselineBetter");
  return fill("verdictNotDistinguishable");
}

/** "Export figures" — exactly what the screen is showing, nothing recomputed. */
function exportFigures(data: MetricsOverview): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "estimo-calibration.json";
  link.click();
  URL.revokeObjectURL(url);
}

function Tile({
  label,
  value,
  hint,
  last,
}: {
  label: string;
  value: string;
  hint?: string;
  last?: boolean;
}) {
  return (
    <div
      style={{
        padding: "14px 16px",
        borderRight: last ? undefined : "1px solid var(--line)",
      }}
    >
      <Lbl>{label}</Lbl>
      <div style={{ marginTop: 6 }}>
        <Num style={{ textAlign: "left", fontSize: 22, fontWeight: 600 }}>
          {value}
        </Num>
      </div>
      {hint && (
        <div
          style={{
            fontSize: 11.5,
            color: "var(--ink2)",
            marginTop: 4,
            textWrap: "pretty",
          }}
        >
          {hint}
        </div>
      )}
    </div>
  );
}

const W = 620;
const H = 190;
const PAD = { left: 38, right: 14, top: 10, bottom: 22 };

function CoverageChart({
  series,
}: {
  series: MetricsOverview["calibration"]["series"];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const points = series.filter((snap) => snap.rolling_coverage !== null);
  if (points.length === 0) {
    return (
      <div style={{ fontSize: 12.5, color: "var(--mut)" }}>
        {t("noData")}
      </div>
    );
  }
  const x = (index: number) =>
    PAD.left +
    (points.length === 1
      ? (W - PAD.left - PAD.right) / 2
      : (index * (W - PAD.left - PAD.right)) / (points.length - 1));
  const y = (value: number) =>
    PAD.top + (1 - value) * (H - PAD.top - PAD.bottom);
  const nominal = points[0].nominal;
  const path = points
    .map(
      (snap, index) =>
        `${index === 0 ? "M" : "L"}${x(index)},${y(snap.rolling_coverage as number)}`,
    )
    .join(" ");

  return (
    <>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto" }}
        role="img"
        aria-label={t("coverageChartTitle")}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - rect.left) / rect.width) * W;
          let nearest = 0;
          for (let index = 1; index < points.length; index++) {
            if (Math.abs(x(index) - px) < Math.abs(x(nearest) - px))
              nearest = index;
          }
          setHover(nearest);
        }}
      >
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--line)"
              strokeWidth={1}
            />
            <text x={2} y={y(tick) + 4} fill="var(--mut)" fontSize={10.5}>
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y(nominal)}
          y2={y(nominal)}
          stroke="var(--mut)"
          strokeWidth={1.5}
          strokeDasharray="6 4"
        />
        <text
          x={W - PAD.right - 2}
          y={y(nominal) - 5}
          fill="var(--mut)"
          fontSize={10.5}
          textAnchor="end"
        >
          {t("nominalWord")} {Math.round(nominal * 100)}%
        </text>
        <path d={path} fill="none" stroke="var(--acc)" strokeWidth={2} />
        {points.map((snap, index) => (
          <circle
            key={snap.at}
            cx={x(index)}
            cy={y(snap.rolling_coverage as number)}
            r={hover === index ? 5 : 3}
            fill="var(--acc)"
            stroke="var(--surf)"
            strokeWidth={2}
          />
        ))}
        {hover !== null && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={H - PAD.bottom}
            stroke="var(--mut)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
        )}
      </svg>
      {hover !== null && (
        <Mn style={{ color: "var(--ink2)" }}>
          {/* `samples` on a snapshot is the TRANSFER-DISTRIBUTION count over a
              different population; pairing it with this rate rendered a 3-row 33%
              coverage as "33% · n=33". Snapshots written before migration 0016 carry
              no rolling count and show none. */}
          {new Date(points[hover].at).toLocaleString(DATE_LOCALE)} ·{" "}
          {Math.round((points[hover].rolling_coverage as number) * 100)}%
          {points[hover].rolling_samples !== null &&
            ` · ${t("samplesShort")}=${points[hover].rolling_samples}`}
        </Mn>
      )}
    </>
  );
}

function MaeBars({
  product,
  naive,
}: {
  product: number | null;
  naive: number | null;
}) {
  if (product === null && naive === null) {
    return (
      <div style={{ fontSize: 12.5, color: "var(--mut)" }}>
        {t("noData")}
      </div>
    );
  }
  const max = Math.max(product ?? 0, naive ?? 0, 0.1);
  const rows: [string, number | null, string][] = [
    ["Estimo", product, "var(--acc)"],
    [t("naiveMedian"), naive, "var(--line2)"],
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map(([label, value, colour]) => (
        <div
          key={label}
          style={{ display: "flex", alignItems: "center", gap: 10 }}
        >
          <div style={{ width: 108, flex: "none", fontSize: 12.5 }}>
            {label}
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
                width: `${((value ?? 0) / max) * 100}%`,
                height: "100%",
                background: colour,
              }}
            />
          </div>
          <Num style={{ width: 72, flex: "none" }}>
            {value === null ? "—" : `${value} pd`}
          </Num>
        </div>
      ))}
    </div>
  );
}
