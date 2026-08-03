"use client";

/** App chrome: the sticky top bar and the 184px left rail from the design.
 *
 * The design is explicit that this is a desktop workstation UI (min-width 1280px,
 * no mobile breakpoint), that theme and density are root data attributes, and that
 * rail icons are CSS primitives rather than glyph fonts. */

import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { detectLocale, setLocale, t, type Locale } from "@/lib/i18n";

type Theme = "light" | "dark";
type Density = "dense" | "comfortable";

const RAIL: { href: string; key: "estimates" | "ledger" | "calibration" | "knowledge" | "admin" }[] =
  [
    { href: "/", key: "estimates" },
    { href: "/ledger", key: "ledger" },
    { href: "/calibration", key: "calibration" },
    { href: "/knowledge", key: "knowledge" },
    { href: "/admin", key: "admin" },
  ];

function RailIcon() {
  // CSS primitive, per the design — no icon font, no emoji.
  return (
    <span
      aria-hidden
      style={{
        width: 14,
        height: 14,
        border: "1.5px solid currentColor",
        borderRadius: 3,
        flex: "none",
      }}
    />
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [locale, setLocaleState] = useState<Locale>("en");
  const [theme, setTheme] = useState<Theme>("light");
  const [density, setDensity] = useState<Density>("dense");

  useEffect(() => {
    setLocaleState(detectLocale());
    const storedTheme = window.localStorage.getItem("estimo-theme");
    const storedDensity = window.localStorage.getItem("estimo-density");
    const initialTheme: Theme =
      storedTheme === "dark" || storedTheme === "light"
        ? storedTheme
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    const initialDensity: Density =
      storedDensity === "comfortable" || storedDensity === "dense" ? storedDensity : "dense";
    setTheme(initialTheme);
    setDensity(initialDensity);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("estimo-theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.density = density;
    window.localStorage.setItem("estimo-density", density);
  }, [density]);

  const switchLocale = useCallback((next: Locale) => {
    setLocale(next);
    setLocaleState(next);
  }, []);

  const active = (href: string) =>
    href === "/" ? pathname === "/" || pathname.startsWith("/estimates") : pathname.startsWith(href);

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 50,
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "10px 22px",
          background: "var(--surf)",
          borderBottom: "1px solid var(--line2)",
          boxShadow: "var(--sh)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
          <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.01em" }}>Estimo</span>
          <span className="lbl">{t(locale, "tagline")}</span>
        </div>
        <div style={{ flex: 1 }} />
        <select
          aria-label="Language"
          value={locale}
          onChange={(event) => switchLocale(event.target.value as Locale)}
          style={{ fontSize: 12.5 }}
        >
          <option value="en">EN</option>
          <option value="tr">TR</option>
        </select>
        <button
          type="button"
          className="btn"
          onClick={() => setDensity(density === "dense" ? "comfortable" : "dense")}
        >
          {density === "dense" ? t(locale, "densityComfortable") : t(locale, "densityDense")}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
        >
          {theme === "light" ? t(locale, "themeDark") : t(locale, "themeLight")}
        </button>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <nav
          style={{
            width: 184,
            flex: "none",
            borderRight: "1px solid var(--line)",
            background: "var(--surf2)",
            padding: "12px 10px",
            display: "flex",
            flexDirection: "column",
            gap: 3,
          }}
        >
          {RAIL.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`rail-i ${active(item.href) ? "on" : ""}`.trim()}
            >
              <RailIcon />
              {t(locale, item.key)}
            </Link>
          ))}
          <div style={{ flex: 1, minHeight: 36 }} />
        </nav>

        <main style={{ flex: 1, minWidth: 0, padding: "18px 22px 60px" }}>{children}</main>
      </div>
    </div>
  );
}
