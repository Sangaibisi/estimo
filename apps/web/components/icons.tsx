/** Estimo icon set — inline SVG, stroke-based, drawn on a 16px grid.
 *
 * Identity rules (docs/design/README.md, "Identity layer"):
 * - No icon font, no emoji glyphs — every icon is an inline SVG using
 *   `currentColor`, so rail/active/muted states color them like text.
 * - 1.5px strokes, round caps, geometry aligned to the half-pixel grid so the
 *   icons stay crisp at 16px on 1x displays.
 * - The logo mark is the ONE place the brand gradient is a fill; everywhere else
 *   gradients stay on chrome (top strip, washes), never inside data graphics.
 */

import { useId, type CSSProperties } from "react";

interface IconProps {
  size?: number;
  style?: CSSProperties;
}

function Svg({
  size = 16,
  style,
  children,
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      aria-hidden
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flex: "none", ...style }}
    >
      {children}
    </svg>
  );
}

/** Brand mark — mirrors app/icon.svg (the favicon); keep the two in sync.
 *
 * Deliberately FIXED colors, not theme tokens: the favicon cannot adapt to the
 * theme, and the dark theme's lightened accent would wash the white bars out —
 * the tile stays deep navy everywhere, like any printed logo. */
export function LogoMark({ size = 22, style }: IconProps) {
  const id = useId();
  return (
    <svg
      aria-hidden
      width={size}
      height={size}
      viewBox="0 0 32 32"
      style={{ flex: "none", ...style }}
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a06ee8" />
          <stop offset="1" stopColor="#5b2ea6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${id})`} />
      <rect
        x="8"
        y="8.6"
        width="10"
        height="3.4"
        rx="1.7"
        fill="#fff"
        opacity="0.75"
      />
      <rect x="8" y="14.3" width="16" height="3.4" rx="1.7" fill="#fff" />
      <rect
        x="8"
        y="20"
        width="13"
        height="3.4"
        rx="1.7"
        fill="#fff"
        opacity="0.75"
      />
    </svg>
  );
}

/** Estimates — a BRD document with its fold. */
export function IconEstimates(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 1.75h5.25L12.5 5v9.25H4z" />
      <path d="M9.25 1.75V5h3.25" />
      <path d="M6 8.5h4.5M6 11h4.5" />
    </Svg>
  );
}

/** Ledger — dated entries, one row per delivered item. */
export function IconLedger(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="3.5" cy="4" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="3.5" cy="8" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="3.5" cy="12" r="0.9" fill="currentColor" stroke="none" />
      <path d="M6.5 4h6.5M6.5 8h6.5M6.5 12h6.5" />
    </Svg>
  );
}

/** Import — a file taken in through a gate: the seed-set wizard's affordance. */
export function IconImport(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 2.25v7.5" />
      <path d="M5.25 7l2.75 2.75L10.75 7" />
      <path d="M2.75 11.25v1.5a1 1 0 0 0 1 1h8.5a1 1 0 0 0 1-1v-1.5" />
    </Svg>
  );
}

/** Calibration — a target: are our ranges honest? */
export function IconCalibration(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="5.75" />
      <circle cx="8" cy="8" r="2.75" />
      <circle cx="8" cy="8" r="0.9" fill="currentColor" stroke="none" />
    </Svg>
  );
}

/** Knowledge — layered sources distilled into pages. */
export function IconKnowledge(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 1.9 14 5.2 8 8.5 2 5.2z" />
      <path d="m2 8.6 6 3.3 6-3.3" />
      <path d="m2 11.6 6 3.3 6-3.3" />
    </Svg>
  );
}

/** Admin — sliders: boring but transparent. Knobs are solid currentColor dots
 * (a surface-colored knockout would show as wrong-colored discs on hover/active
 * backgrounds and break the icon set's currentColor contract). */
export function IconAdmin(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2 4.25h12M2 8h12M2 11.75h12" />
      <circle cx="10.5" cy="4.25" r="1.7" fill="currentColor" stroke="none" />
      <circle cx="5.5" cy="8" r="1.7" fill="currentColor" stroke="none" />
      <circle cx="11.5" cy="11.75" r="1.7" fill="currentColor" stroke="none" />
    </Svg>
  );
}

/** Repository map — three typed nodes and the edges that relate them. */
export function IconMap(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="1.75" y="2.5" width="5" height="3.5" rx="1" />
      <rect x="9.25" y="6.25" width="5" height="3.5" rx="1" />
      <rect x="1.75" y="10" width="5" height="3.5" rx="1" />
      <path d="M6.75 4.5c2.5 0 2.5 3.25 2.5 3.25M6.75 11.5c2.5 0 2.5-3 2.5-3" />
    </Svg>
  );
}

/* ---------------- Connector marks (S13 polish) ----------------
 *
 * Per-provider identity for the Admin → Connections tiles. Hand-drawn,
 * simplified renditions on the same 16px grid — NOT the providers' official
 * assets — with one fixed accent per provider. These are the single exception
 * to the currentColor rule: a connector's identity color must not re-tint with
 * the rail state, or every provider looks like "the active one".
 */

const CONNECTOR_ACCENTS: Record<string, string> = {
  github: "#8b949e",
  gitlab: "#fc6d26",
  bitbucket: "#2684ff",
  git: "#f05033",
  confluence: "#2684ff",
  jira: "#2684ff",
};

function markGlyph(kind: string): React.ReactNode {
  switch (kind) {
    case "github":
      // Cat-head silhouette, simplified: round head, two ears.
      return (
        <path
          d="M8 2.6c-3 0-5.4 2.4-5.4 5.4 0 2.4 1.5 4.4 3.7 5.1v-1.8c-.5.1-1.1 0-1.4-.5-.2-.3-.4-.7-.7-.9.5-.2 1 .2 1.3.6.4.6 1 .5 1.4.4.1-.4.3-.7.5-.9-1.7-.2-2.9-.9-2.9-2.7 0-.6.2-1.1.6-1.5-.1-.2-.3-.9.1-1.6 0 0 .5-.2 1.7.6a5.7 5.7 0 0 1 2.9 0c1.2-.8 1.7-.6 1.7-.6.4.7.2 1.4.1 1.6.4.4.6.9.6 1.5 0 1.8-1.2 2.5-2.9 2.7.3.3.5.7.5 1.3v2c2.2-.7 3.7-2.7 3.7-5.1 0-3-2.4-5.4-5.4-5.4z"
          fill="currentColor"
          stroke="none"
        />
      );
    case "gitlab":
      // The tanuki reduced to its pentagon-arrow silhouette.
      return (
        <path
          d="M8 13.6 2.8 9.8c-.3-.2-.4-.6-.3-.9l1.1-3.4 1.5 4h5.8l1.5-4 1.1 3.4c.1.3 0 .7-.3.9L8 13.6z"
          fill="currentColor"
          stroke="none"
        />
      );
    case "bitbucket":
      // The tilted-bucket mark: outer wedge with a knocked-out center.
      return (
        <path
          d="M2.9 3h10.2c.3 0 .5.3.5.6l-1.7 9c-.1.3-.3.5-.6.5H4.7c-.3 0-.5-.2-.6-.5l-1.7-9c0-.3.2-.6.5-.6zm3.6 3.4.6 3.4h1.8l.6-3.4H6.5z"
          fill="currentColor"
          stroke="none"
          fillRule="evenodd"
        />
      );
    case "confluence":
      // Two converging waves.
      return (
        <>
          <path d="M2.5 11.5c1.6-2.6 3-3.2 5.5-2l3 1.4" fill="none" />
          <path d="M13.5 4.5c-1.6 2.6-3 3.2-5.5 2L5 5.1" fill="none" />
        </>
      );
    case "jira":
      // Two stacked diamonds converging on the mark's point.
      return (
        <>
          <path
            d="M8 2.5 11.3 5.8 8 9 4.7 5.8 8 2.5z"
            fill="currentColor"
            stroke="none"
          />
          <path
            d="M8 9.6l2.2 2.2L8 14l-2.2-2.2L8 9.6z"
            fill="currentColor"
            stroke="none"
            opacity={0.55}
          />
        </>
      );
    default:
      // Plain git (or unknown): a branch fork.
      return (
        <>
          <circle cx="4.5" cy="3.8" r="1.4" fill="none" />
          <circle cx="4.5" cy="12.2" r="1.4" fill="none" />
          <circle cx="11.5" cy="6" r="1.4" fill="none" />
          <path d="M4.5 5.2v5.6M11.5 7.4c0 2.4-3 2.2-5 3.2" fill="none" />
        </>
      );
  }
}

/** Provider badge: tinted rounded square + the provider glyph in its accent. */
export function ConnectorMark({ kind, size = 26 }: { kind: string; size?: number }) {
  const accent = CONNECTOR_ACCENTS[kind] ?? "var(--mut)";
  return (
    <span
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: 7,
        flex: "none",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        color: accent,
        background: `color-mix(in srgb, ${accent} 13%, transparent)`,
        border: `1px solid color-mix(in srgb, ${accent} 28%, transparent)`,
      }}
    >
      <svg
        width={size - 10}
        height={size - 10}
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {markGlyph(kind)}
      </svg>
    </span>
  );
}

/** Proper display names for connector kinds ("github" → "GitHub"). */
export const CONNECTOR_LABELS: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  bitbucket: "Bitbucket",
  git: "Git",
  confluence: "Confluence",
  jira: "Jira",
};
