"use client";

/** 8 · Calibration Dashboard — "Are our ranges honest? The product grades itself."
 *
 * Design rules honoured: every rate ships with its sample count, the naive baseline
 * sits beside the product's own number (PRINCIPLES #7), and the copy states the
 * result against its target even when the product is losing. */

import { useEffect, useState } from "react";
import { api, type MetricsOverview } from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, Num, StatusChip } from "@/components/ui";

export default function CalibrationPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [data, setData] = useState<MetricsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLocale(detectLocale());
    api.metrics().then(setData).catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <section className="scr">
        <div role="alert" className="card" style={{ padding: 16, color: "var(--crit)" }}>
          {error}
        </div>
      </section>
    );
  }
  if (!data) return <p className="muted">…</p>;

  const { calibration, product_accuracy, anchoring, workflow } = data;
  const pct = (value: number | null) => (value === null ? "—" : `${Math.round(value * 100)}%`);
  const coverageOnTarget =
    product_accuracy.coverage !== null &&
    product_accuracy.coverage >= product_accuracy.nominal - 0.05;

  return (
    <section className="scr">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 19, fontWeight: 600, letterSpacing: "-0.01em" }}>
          {t(locale, "calibration")}
        </h2>
        <span style={{ fontSize: 13, color: "var(--mut)" }}>
          {t(locale, "calibrationSubtitle")}
        </span>
      </div>

      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title={t(locale, "howHonest")}
          subtitle={
            product_accuracy.samples === 0
              ? t(locale, "noData")
              : `${product_accuracy.samples} ${t(locale, "completedItems")}`
          }
          right={
            product_accuracy.coverage !== null ? (
              <StatusChip status={coverageOnTarget ? "ok" : "warn"}>
                {t(locale, "coverageVsTarget")
                  .replace("{actual}", pct(product_accuracy.coverage))
                  .replace("{target}", pct(product_accuracy.nominal))}
              </StatusChip>
            ) : (
              <Chip>{t(locale, "noCoverageYet")}</Chip>
            )
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
            <Lbl>{t(locale, "coverageChartTitle")}</Lbl>
            <div style={{ fontSize: 12, color: "var(--mut)", margin: "4px 0 10px" }}>
              {t(locale, "coverageChartHint")}
            </div>
            <CoverageChart locale={locale} series={calibration.series} />
            {calibration.current.samples < 100 && (
              <div style={{ fontSize: 12, color: "var(--ink2)", marginTop: 8, textWrap: "pretty" }}>
                {t(locale, "lowSampleNote")}
              </div>
            )}
          </div>

          <div style={{ width: 420, flex: "none", padding: "14px 18px" }}>
            <Lbl>{t(locale, "maeChartTitle")}</Lbl>
            <div style={{ fontSize: 12, color: "var(--mut)", margin: "4px 0 10px" }}>
              {t(locale, "maeChartHint")}
            </div>
            <MaeBars
              locale={locale}
              product={product_accuracy.mae_product}
              naive={product_accuracy.mae_naive_median}
            />

            <div style={{ marginTop: 18 }}>
              <Lbl>{t(locale, "transferQuantiles")}</Lbl>
              <table className="dt" style={{ marginTop: 8 }}>
                <thead>
                  <tr>
                    <th>q10</th>
                    <th>q50</th>
                    <th>q90</th>
                    <th style={{ width: 60 }}>{t(locale, "samplesShort")}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="num">{calibration.current.q10.toFixed(2)}</td>
                    <td className="num">{calibration.current.q50.toFixed(2)}</td>
                    <td className="num">{calibration.current.q90.toFixed(2)}</td>
                    <td className="num">{calibration.current.samples}</td>
                  </tr>
                </tbody>
              </table>
              {calibration.current.prior_based && (
                <div style={{ marginTop: 8 }}>
                  <StatusChip status="warn">{t(locale, "priorBased")}</StatusChip>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <BandHeader
          title={t(locale, "anchoringSection")}
          subtitle={t(locale, "anchoringSubtitle")}
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)" }}>
          <Tile
            label={`${t(locale, "anchoringTile")} · ${t(locale, "samplesShort")}=${anchoring.samples}`}
            value={anchoring.mean_abs_delta === null ? "—" : `${anchoring.mean_abs_delta} pd`}
          />
          <Tile
            label={t(locale, "zeroDeltaTile")}
            value={pct(anchoring.zero_delta_share)}
            hint={t(locale, "zeroDeltaHint")}
          />
          <Tile label={t(locale, "wipTile")} value={String(workflow.wip)} />
          <Tile label={t(locale, "revisionTile")} value={pct(workflow.question_revision_rate)} />
          <Tile label={t(locale, "rebuildTile")} value={pct(workflow.rebuild_share)} last />
        </div>
      </div>
    </section>
  );
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
    <div style={{ padding: "14px 16px", borderRight: last ? undefined : "1px solid var(--line)" }}>
      <Lbl>{label}</Lbl>
      <div style={{ marginTop: 6 }}>
        <Num style={{ textAlign: "left", fontSize: 22, fontWeight: 600 }}>{value}</Num>
      </div>
      {hint && (
        <div style={{ fontSize: 11.5, color: "var(--ink2)", marginTop: 4, textWrap: "pretty" }}>
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
  locale,
  series,
}: {
  locale: Locale;
  series: MetricsOverview["calibration"]["series"];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const points = series.filter((snap) => snap.rolling_coverage !== null);
  if (points.length === 0) {
    return <div style={{ fontSize: 12.5, color: "var(--mut)" }}>{t(locale, "noData")}</div>;
  }
  const x = (index: number) =>
    PAD.left +
    (points.length === 1
      ? (W - PAD.left - PAD.right) / 2
      : (index * (W - PAD.left - PAD.right)) / (points.length - 1));
  const y = (value: number) => PAD.top + (1 - value) * (H - PAD.top - PAD.bottom);
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
        aria-label={t(locale, "coverageChartTitle")}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - rect.left) / rect.width) * W;
          let nearest = 0;
          for (let index = 1; index < points.length; index++) {
            if (Math.abs(x(index) - px) < Math.abs(x(nearest) - px)) nearest = index;
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
          {t(locale, "nominalWord")} {Math.round(nominal * 100)}%
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
          {new Date(points[hover].at).toLocaleString(locale)} ·{" "}
          {Math.round((points[hover].rolling_coverage as number) * 100)}% ·{" "}
          {t(locale, "samplesShort")}={points[hover].samples}
        </Mn>
      )}
    </>
  );
}

function MaeBars({
  locale,
  product,
  naive,
}: {
  locale: Locale;
  product: number | null;
  naive: number | null;
}) {
  if (product === null && naive === null) {
    return <div style={{ fontSize: 12.5, color: "var(--mut)" }}>{t(locale, "noData")}</div>;
  }
  const max = Math.max(product ?? 0, naive ?? 0, 0.1);
  const rows: [string, number | null, string][] = [
    ["Estimo", product, "var(--acc)"],
    [t(locale, "naiveMedian"), naive, "var(--line2)"],
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map(([label, value, colour]) => (
        <div key={label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 108, flex: "none", fontSize: 12.5 }}>{label}</div>
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
              style={{ width: `${((value ?? 0) / max) * 100}%`, height: "100%", background: colour }}
            />
          </div>
          <Num style={{ width: 72, flex: "none" }}>{value === null ? "—" : `${value} pd`}</Num>
        </div>
      ))}
    </div>
  );
}
