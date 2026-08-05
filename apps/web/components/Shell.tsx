"use client";

/** App chrome — the design's left sidebar (docs/design/repository-map.dc.html).
 *
 * One dark theme, English-only UI, no top bar: the sidebar is the whole chrome.
 * Two nav groups: WORKSPACE (the estimation surfaces) and, pinned to the bottom as
 * its own category, ADMIN — visible only to a platform admin, because Settings is
 * where connections and the model gateway live. Below it sits the session card: who
 * you are, which workspace you are acting in, and the way out.
 *
 * Behind everything is the ambient layer — the design's violet radial plus two very
 * slow drifting orbs (`om-drift-*`, disabled under prefers-reduced-motion). */

import type { CSSProperties, ReactNode } from "react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, type TenantEntry } from "@/lib/api";
import { ROLE_LABELS, setActingTenant, signOut } from "@/lib/auth";
import { SessionProvider, useSession } from "@/components/Session";
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
  return (
    <SessionProvider>
      <Chrome>{children}</Chrome>
    </SessionProvider>
  );
}

function Chrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const session = useSession();
  const isPlatformAdmin = session.role === "platform_admin";

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
            only (connections, model gateway, accounts). */}
        {(isPlatformAdmin || !session.accountsExist) && (
          <div style={{ padding: "10px 8px 0", display: "flex", flexDirection: "column", gap: 3 }}>
            <div style={{ height: 1, background: "var(--line)", margin: "0 6px 10px" }} />
            <div style={groupLabel}>ADMIN</div>
            {item({ href: "/admin", label: "Settings", icon: IconAdmin })}
          </div>
        )}

        <SessionCard />
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

/** Who you are, where you are acting, and the way out. */
function SessionCard() {
  const session = useSession();
  const [tenants, setTenants] = useState<TenantEntry[]>([]);

  // Only a platform admin may act inside another workspace, so only a platform
  // admin is offered the switch (and only when there is more than one).
  useEffect(() => {
    if (session.role !== "platform_admin") return;
    api
      .listTenants()
      .then(setTenants)
      .catch(() => setTenants([]));
  }, [session.role, session.tenant]);

  if (!session.user) {
    return (
      <div style={{ padding: "12px 14px 16px" }}>
        <div style={{ height: 1, background: "var(--line)", marginBottom: 12 }} />
        <div style={{ fontSize: 11.5, color: "var(--mut)", textWrap: "pretty" }}>
          No accounts yet — this deployment is open. Claim it in Settings.
        </div>
      </div>
    );
  }

  const initials = session.user.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join("");

  return (
    <div style={{ padding: "12px 14px 16px" }}>
      <div style={{ height: 1, background: "var(--line)", marginBottom: 12 }} />

      {session.role === "platform_admin" && tenants.length > 1 && (
        <label style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 10 }}>
          <span style={{ ...groupLabel, padding: 0, marginBottom: 0 }}>WORKSPACE</span>
          <select
            value={session.tenant ?? ""}
            onChange={(event) => {
              setActingTenant(
                event.target.value === session.user?.tenant_id ? null : event.target.value,
              );
              // A workspace switch changes what every screen is about, so the whole
              // app reloads rather than leaving stale rows from the previous one.
              window.location.reload();
            }}
            style={{ fontSize: 11, padding: "5px 7px" }}
          >
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span
          aria-hidden
          style={{
            width: 28,
            height: 28,
            flex: "none",
            borderRadius: 8,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            background: "oklch(0.26 0.03 300)",
            color: "oklch(0.84 0.1 300)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {initials || "?"}
        </span>
        <span style={{ minWidth: 0, flex: 1 }}>
          <span
            style={{
              display: "block",
              fontSize: 12,
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {session.user.name}
          </span>
          <span style={{ display: "block", fontSize: 10, color: "var(--mut)" }}>
            {ROLE_LABELS[session.user.role] ?? session.user.role}
            {session.user.can_sign ? " · signs" : ""}
          </span>
        </span>
      </div>
      <button
        type="button"
        className="btn"
        style={{ width: "100%", justifyContent: "center", marginTop: 10, padding: "5px 10px" }}
        onClick={() => {
          signOut();
          window.location.href = "/";
        }}
      >
        Sign out
      </button>
    </div>
  );
}
