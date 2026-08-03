"use client";

/** App chrome: the sticky top bar and the 184px left rail from the design.
 *
 * The design is explicit that this is a desktop workstation UI (min-width 1280px,
 * no mobile breakpoint) and that theme and density are root data attributes. The
 * identity layer (docs/design/README.md) replaced the original CSS-primitive rail
 * squares with the drawn SVG icon set — still no glyph font, no emoji. */

import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { detectLocale, setLocale, t, type Locale } from "@/lib/i18n";
import {
  IconAdmin,
  IconCalibration,
  IconEstimates,
  IconKnowledge,
  IconLedger,
  IconMoon,
  IconSun,
  LogoMark,
} from "@/components/icons";

type Theme = "light" | "dark";
type Density = "dense" | "comfortable";

const RAIL: {
  href: string;
  key: "estimates" | "ledger" | "calibration" | "knowledge" | "admin";
  icon: (props: { size?: number }) => ReactNode;
}[] = [
  { href: "/", key: "estimates", icon: IconEstimates },
  { href: "/ledger", key: "ledger", icon: IconLedger },
  { href: "/calibration", key: "calibration", icon: IconCalibration },
  { href: "/knowledge", key: "knowledge", icon: IconKnowledge },
  { href: "/admin", key: "admin", icon: IconAdmin },
];

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
    // CSS text-transform cases by the CONTENT language: Turkish uppercases i → İ
    // only when the tree is marked tr, otherwise every uppercased label ships the
    // wrong glyph ("PROFILI" for "PROFİLİ").
    document.documentElement.lang = locale;
  }, [locale]);

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
        className="topbar"
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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <LogoMark size={24} />
          <span style={{ fontSize: 15.5, fontWeight: 600, letterSpacing: "-0.01em" }}>
            Estimo
          </span>
          <span className="lbl" style={{ alignSelf: "center", paddingTop: 1 }}>
            {t(locale, "tagline")}
          </span>
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
          {theme === "light" ? <IconMoon size={14} /> : <IconSun size={14} />}
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
              <item.icon size={16} />
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
