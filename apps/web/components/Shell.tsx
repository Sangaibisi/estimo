"use client";

/** App chrome — the design's left sidebar (docs/design/repository-map.dc.html).
 *
 * One dark theme, English-only UI, no top bar: the sidebar is the whole chrome.
 * Two nav groups: WORKSPACE (the estimation surfaces) and, pinned to the bottom
 * as its own category, ADMIN (deployment settings only). Behind everything sits
 * the ambient layer — the design's violet radial plus two very slow drifting
 * orbs (`om-drift-*`, disabled under prefers-reduced-motion). */

import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  IconAdmin,
  IconCalibration,
  IconEstimates,
  IconKnowledge,
  IconLedger,
  IconMap,
  LogoMark,
} from "@/components/icons";

const WORKSPACE: {
  href: string;
  label: string;
  icon: (props: { size?: number }) => ReactNode;
}[] = [
  { href: "/", label: "Estimates", icon: IconEstimates },
  { href: "/map", label: "Repository map", icon: IconMap },
  { href: "/ledger", label: "Ledger", icon: IconLedger },
  { href: "/calibration", label: "Calibration", icon: IconCalibration },
  { href: "/knowledge", label: "Knowledge", icon: IconKnowledge },
];

const groupLabel: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 9.5,
  letterSpacing: "0.18em",
  color: "var(--mut)",
  padding: "0 12px",
  marginBottom: 6,
};

function orb(color: string, size: number, pos: CSSProperties, anim: string): CSSProperties {
  return {
    position: "absolute",
    width: size,
    height: size,
    borderRadius: "50%",
    background: `radial-gradient(circle, ${color}, transparent 70%)`,
    filter: "blur(70px)",
    opacity: 0.55,
    animation: `${anim} linear infinite`,
    ...pos,
  };
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  const active = (href: string) =>
    href === "/" ? pathname === "/" || pathname.startsWith("/estimates") : pathname.startsWith(href);

  const item = (entry: (typeof WORKSPACE)[number]) => (
    <Link
      key={entry.href}
      href={entry.href}
      className={`rail-i ${active(entry.href) ? "on" : ""}`.trim()}
    >
      <entry.icon size={16} />
      {entry.label}
    </Link>
  );

  return (
    <div style={{ height: "100vh", display: "flex", overflow: "hidden" }}>
      {/* Ambient layer: the design's violet radial + two slow orbs. */}
      <div
        aria-hidden
        className="om-anim"
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 0,
          pointerEvents: "none",
          background:
            "radial-gradient(120% 90% at 30% 0%, oklch(0.2 0.03 300) 0%, var(--bg) 62%)",
          overflow: "hidden",
        }}
      >
        <div
          style={orb(
            "oklch(0.4 0.13 300 / 0.5)",
            560,
            { top: "-12%", left: "8%" },
            "om-drift-a 52s",
          )}
        />
        <div
          style={orb(
            "oklch(0.4 0.1 200 / 0.35)",
            480,
            { bottom: "-18%", right: "-6%" },
            "om-drift-b 67s",
          )}
        />
      </div>

      <nav
        style={{
          width: 224,
          flex: "none",
          zIndex: 2,
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid var(--line)",
          background: "linear-gradient(180deg, oklch(0.185 0.016 295), oklch(0.165 0.012 295))",
          overflowY: "auto",
        }}
      >
        <Link
          href="/"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 11,
            padding: "16px 16px",
            borderBottom: "1px solid var(--line)",
            color: "var(--ink)",
          }}
        >
          <LogoMark size={26} />
          <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 13.5, fontWeight: 700, letterSpacing: "-0.01em" }}>
              Estimo
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 8.5,
                color: "var(--mut)",
                letterSpacing: "0.16em",
              }}
            >
              BASIS OF ESTIMATE
            </span>
          </span>
        </Link>

        <div style={{ padding: "16px 8px 8px", display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={groupLabel}>WORKSPACE</div>
          {WORKSPACE.map(item)}
        </div>

        <div style={{ flex: 1, minHeight: 24 }} />

        {/* Admin lives at the bottom, as its own category — deployment settings
            only (connections + model gateway), away from the daily surfaces. */}
        <div style={{ padding: "10px 8px 14px", display: "flex", flexDirection: "column", gap: 3 }}>
          <div style={{ height: 1, background: "var(--line)", margin: "0 6px 10px" }} />
          <div style={groupLabel}>ADMIN</div>
          {item({ href: "/admin", label: "Settings", icon: IconAdmin })}
        </div>
      </nav>

      <main
        style={{
          flex: 1,
          minWidth: 0,
          zIndex: 1,
          overflow: "auto",
          padding: "18px 22px 60px",
        }}
      >
        {children}
      </main>
    </div>
  );
}
