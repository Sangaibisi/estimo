"use client";

/** Honesty dashboards (S8-3): coverage vs nominal, anchoring telemetry, naive
 * comparison, workflow second-order signals. Single-series charts by design —
 * the design tokens are not a validated categorical set, so identity never rides
 * on color alone (dataviz discipline); status colors appear only with labels. */

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type MetricsOverview } from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";

export default function DashboardPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [data, setData] = useState<MetricsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLocale(detectLocale());
    api.metrics().then(setData).catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <main>
        <p style={{ color: "var(--crit)" }} role="alert">
          {error}
        </p>
      </main>
    );
  }
  if (!data) return <p className="muted">…</p>;

  const { calibration, product_accuracy, anchoring, workflow } = data;
  const pct = (value: number | null) =>
    value === null ? "—" : `${Math.round(value * 100)}%`;

  return (
    <main>
      <p>
        <Link href="/">← {t(locale, "estimates")}</Link>
      </p>
      <h1>{t(locale, "dashboard")}</h1>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <StatTile
          label={`${t(locale, "coverageChartTitle")} (${t(locale, "samplesShort")}=${product_accuracy.samples})`}
          value={pct(product_accuracy.coverage)}
          hint={`nominal ${pct(product_accuracy.nominal)}`}
        />
        <StatTile
          label={`${t(locale, "anchoringTile")} (${t(locale, "samplesShort")}=${anchoring.samples})`}
          value={anchoring.mean_abs_delta === null ? "—" : `${anchoring.mean_abs_delta} pd`}
        />
        <StatTile
          label={t(locale, "zeroDeltaTile")}
          value={pct(anchoring.zero_delta_share)}
          hint={t(locale, "zeroDeltaHint")}
        />
        <StatTile label={t(locale, "wipTile")} value={String(workflow.wip)} />
        <StatTile
          label={t(locale, "revisionTile")}
          value={pct(workflow.question_revision_rate)}
        />
        <StatTile label={t(locale, "rebuildTile")} value={pct(workflow.rebuild_share)} />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>{t(locale, "coverageChartTitle")}</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          {t(locale, "coverageChartHint")}
        </p>
        <CoverageChart locale={locale} series={calibration.series} />
        {calibration.current.samples < 100 && (
          <p className="muted" style={{ fontSize: 12 }}>
            ⚠ {t(locale, "lowSampleNote")}
          </p>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>{t(locale, "maeChartTitle")}</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          {t(locale, "maeChartHint")}
        </p>
        <MaeChart
          product={product_accuracy.mae_product}
          naive={product_accuracy.mae_naive_median}
          locale={locale}
        />
      </div>
    </main>
  );
}

function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 12 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 600 }}>{value}</div>
      {hint && (
        <div className="muted" style={{ fontSize: 11 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

const W = 640;
const H = 200;
const PAD = { left: 40, right: 12, top: 12, bottom: 24 };

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
    return <p className="muted">{t(locale, "noData")}</p>;
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
            <text x={4} y={y(tick) + 4} fill="var(--mut)" fontSize={11}>
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
        <text x={W - PAD.right - 4} y={y(nominal) - 5} fill="var(--mut)" fontSize={11} textAnchor="end">
          nominal {Math.round(nominal * 100)}%
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
        <p className="muted" style={{ fontSize: 12, margin: "4px 0" }}>
          {new Date(points[hover].at).toLocaleString(locale)} ·{" "}
          {Math.round((points[hover].rolling_coverage as number) * 100)}% ·{" "}
          {t(locale, "samplesShort")}={points[hover].samples}
          {points[hover].prior_based ? " · prior" : ""}
        </p>
      )}
      <details>
        <summary className="muted" style={{ fontSize: 12, cursor: "pointer" }}>
          {t(locale, "tableView")}
        </summary>
        <table>
          <thead>
            <tr>
              <th>t</th>
              <th>coverage</th>
              <th>{t(locale, "samplesShort")}</th>
              <th>q10</th>
              <th>q50</th>
              <th>q90</th>
            </tr>
          </thead>
          <tbody>
            {points.map((snap) => (
              <tr key={snap.at}>
                <td>{new Date(snap.at).toLocaleString(locale)}</td>
                <td>{Math.round((snap.rolling_coverage as number) * 100)}%</td>
                <td>{snap.samples}</td>
                <td>{snap.q10}</td>
                <td>{snap.q50}</td>
                <td>{snap.q90}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function MaeChart({
  product,
  naive,
  locale,
}: {
  product: number | null;
  naive: number | null;
  locale: Locale;
}) {
  if (product === null && naive === null) {
    return <p className="muted">{t(locale, "noData")}</p>;
  }
  const max = Math.max(product ?? 0, naive ?? 0, 0.1);
  const rows: [string, number | null][] = [
    ["Estimo", product],
    ["naive (median)", naive],
  ];
  return (
    <svg viewBox={`0 0 ${W} 96`} style={{ width: "100%", height: "auto" }} role="img">
      {rows.map(([label, value], index) => {
        const barY = 12 + index * 40;
        const width = value === null ? 0 : (value / max) * (W - 240);
        return (
          <g key={label}>
            <text x={4} y={barY + 14} fill="var(--ink)" fontSize={12}>
              {label}
            </text>
          <rect
              x={140}
              y={barY}
              width={Math.max(width, 2)}
              height={20}
              rx={4}
              fill="var(--acc)"
            />
            <text x={148 + width} y={barY + 14} fill="var(--ink)" fontSize={12}>
              {value === null ? "—" : `${value} pd`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
