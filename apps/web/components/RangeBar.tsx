/** The canonical three-point band visual (UI-VISION: RangeBar). Never a lone number. */

import type { ThreePoint } from "@/lib/api";

export function RangeBar({
  band,
  max,
  color = "var(--acc)",
}: {
  band: ThreePoint;
  max: number;
  color?: string;
}) {
  const scale = (value: number) => `${(value / Math.max(max, 0.01)) * 100}%`;
  return (
    <div>
      <div
        style={{
          position: "relative",
          height: 10,
          background: "var(--line)",
          borderRadius: 999,
        }}
      >
        <div
          style={{
            position: "absolute",
            left: scale(band.optimistic),
            width: `calc(${scale(band.pessimistic)} - ${scale(band.optimistic)})`,
            top: 0,
            bottom: 0,
            background: "color-mix(in srgb, " + color + " 30%, transparent)",
            borderRadius: 999,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: `calc(${scale(band.likely)} - 2px)`,
            width: 4,
            top: -2,
            bottom: -2,
            background: color,
            borderRadius: 2,
          }}
        />
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
        {band.optimistic} / <strong style={{ color: "var(--ink)" }}>{band.likely}</strong> /{" "}
        {band.pessimistic} pd
      </div>
    </div>
  );
}
