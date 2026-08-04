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
          <stop offset="0" stopColor="#2b5fa8" />
          <stop offset="1" stopColor="#16355e" />
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

/** Theme toggles. */
export function IconSun(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.13 1.13M11.47 11.47l1.13 1.13M12.6 3.4l-1.13 1.13M4.53 11.47 3.4 12.6" />
    </Svg>
  );
}

export function IconMoon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M13.25 9.6A5.75 5.75 0 1 1 6.4 2.75a4.6 4.6 0 0 0 6.85 6.85z" />
    </Svg>
  );
}
