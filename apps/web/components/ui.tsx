/** Estimo design-system components — the bespoke pieces the spec names.
 *
 * Two rules from the design carry into every component here:
 *  - THREE INDEPENDENT COLOUR ROLES, never blended: neutral surfaces/ink, status
 *    (ok/warn/crit), and evidence type (code/wiki/analog/answer).
 *  - SHAPE CARRIES STATE ALONGSIDE COLOUR: circle = good, diamond = warning,
 *    square = critical. Colour alone never decides.
 */

import type { CSSProperties, ReactNode } from "react";

export function Lbl({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span className="lbl" style={style}>
      {children}
    </span>
  );
}

export function Num({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span className="num" style={style}>
      {children}
    </span>
  );
}

export function Mn({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span className="mn" style={style}>
      {children}
    </span>
  );
}

export function Chip({
  children,
  tone,
  style,
  title,
}: {
  children: ReactNode;
  /** Outline tint only — solid status fills come from StatusChip. */
  tone?: "neutral" | "acc" | "ok" | "warn" | "crit";
  style?: CSSProperties;
  title?: string;
}) {
  const tint: Record<string, CSSProperties> = {
    neutral: {},
    acc: { color: "var(--acc)", borderColor: "var(--acc-line)" },
    ok: { color: "var(--ok)", borderColor: "var(--ok)" },
    warn: { color: "var(--warn)", borderColor: "var(--warn)" },
    crit: { color: "var(--crit)", borderColor: "var(--crit)" },
  };
  return (
    <span className="chip" title={title} style={{ ...tint[tone ?? "neutral"], ...style }}>
      {children}
    </span>
  );
}

/** Status chip: solid tint + a SHAPE, so colour is never the only carrier.
 *  circle = good · diamond = warning · square = critical. */
export function StatusChip({
  status,
  children,
  style,
}: {
  status: "ok" | "warn" | "crit";
  children: ReactNode;
  style?: CSSProperties;
}) {
  const dot: CSSProperties =
    status === "ok"
      ? { borderRadius: "50%" }
      : status === "warn"
        ? { transform: "rotate(45deg)" }
        : {};
  return (
    <span
      className="chip"
      style={{
        color: `var(--${status})`,
        borderColor: `var(--${status})`,
        background: `var(--${status}-bg)`,
        ...style,
      }}
    >
      <span
        aria-hidden
        style={{ width: 7, height: 7, flex: "none", background: `var(--${status})`, ...dot }}
      />
      {children}
    </span>
  );
}

const EVIDENCE_TOKEN: Record<string, string> = {
  code: "var(--ev-code)",
  repo: "var(--ev-code)",
  wiki: "var(--ev-wiki)",
  ledger: "var(--ev-analog)",
  analog: "var(--ev-analog)",
  answer: "var(--ev-ans)",
  note: "var(--mut)",
  canonical: "var(--ev-wiki)",
};

/** Evidence chip: a third colour role. Text tinted, border stays neutral. */
export function EvidenceChip({
  kind,
  label,
  uri,
}: {
  kind: string;
  label?: string | null;
  uri?: string;
}) {
  const colour = EVIDENCE_TOKEN[kind] ?? "var(--mut)";
  return (
    <span className="chip" title={uri} style={{ color: colour, marginRight: 6, marginBottom: 4 }}>
      <span
        aria-hidden
        style={{ width: 8, height: 8, borderRadius: 2, background: colour, flex: "none" }}
      />
      {kind}
      {label ? ` · ${label.slice(0, 38)}` : ""}
    </span>
  );
}

/** RangeBar — the table standard for a three-point range. Never a single number. */
export function RangeBar({
  band,
  max,
  accent = "var(--acc)",
  legend = true,
}: {
  band: { optimistic: number; likely: number; pessimistic: number };
  max: number;
  accent?: string;
  legend?: boolean;
}) {
  const scale = (value: number) => `${Math.min(100, Math.max(0, (value / max) * 100))}%`;
  return (
    <div>
      <div
        style={{
          position: "relative",
          height: 16,
          background: "var(--surf3)",
          borderRadius: 8,
          border: "1px solid var(--line2)",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: scale(band.optimistic),
            right: `calc(100% - ${scale(band.pessimistic)})`,
            top: 0,
            bottom: 0,
            background: "var(--acc-bg)",
            borderLeft: `1px solid ${accent}`,
            borderRight: `1px solid ${accent}`,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: scale(band.likely),
            top: -3,
            bottom: -3,
            width: 3,
            background: accent,
            borderRadius: 2,
          }}
        />
      </div>
      {legend && (
        <div
          className="mn"
          style={{
            display: "flex",
            justifyContent: "space-between",
            color: "var(--mut)",
            marginTop: 3,
          }}
        >
          <span>O {band.optimistic}</span>
          <span style={{ color: accent, fontWeight: 500 }}>L {band.likely}</span>
          <span>P {band.pessimistic}</span>
        </div>
      )}
    </div>
  );
}

export interface Stage {
  key: string;
  label: string;
}

/** StageStrip — a gapless segmented control; segments must touch. */
export function StageStrip({
  stages,
  current,
  done,
  onSelect,
}: {
  stages: Stage[];
  current: string;
  done: (key: string) => boolean;
  onSelect: (key: string) => void;
}) {
  return (
    <div style={{ display: "flex" }}>
      {stages.map((stage) => {
        const state = stage.key === current ? "on" : done(stage.key) ? "done" : "";
        return (
          <button
            key={stage.key}
            type="button"
            className={`stg ${state}`.trim()}
            aria-current={stage.key === current ? "step" : undefined}
            onClick={() => onSelect(stage.key)}
          >
            {stage.label}
          </button>
        );
      })}
    </div>
  );
}

/** Ph — placeholder / drop target. */
export function Ph({
  children,
  style,
}: {
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div className="ph" style={style}>
      {children}
    </div>
  );
}

/** A screen band header: title over a muted subtitle, actions on the right. */
export function BandHeader({
  title,
  subtitle,
  right,
  center,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  center?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 14,
        padding: "11px 18px",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{title}</div>
        {subtitle && (
          <div style={{ fontSize: 12.5, color: "var(--mut)", marginTop: 2 }}>{subtitle}</div>
        )}
      </div>
      {center}
      {right && <div style={{ display: "flex", gap: 8, alignItems: "center" }}>{right}</div>}
    </div>
  );
}
