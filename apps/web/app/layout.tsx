import type { Metadata } from "next";
import type { ReactNode } from "react";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";
import "./tokens.css";
import { Shell } from "@/components/Shell";

// Self-hosted at build time — an air-gapped install must not reach out for fonts.
const sans = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
});
const serif = IBM_Plex_Serif({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "600"],
  variable: "--font-plex-serif",
});

export const metadata: Metadata = {
  title: "Estimo",
  description: "Evidence-linked effort estimation",
};

// Rendered per request so ESTIMO_API_URL is read from the container environment at
// runtime — the browser-visible API origin must never be baked into the image.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: ReactNode }) {
  const apiUrl = process.env.ESTIMO_API_URL ?? "";
  return (
    <html
      lang="en"
      // The design drives theme and row density from root data attributes. The theme
      // toggle in the top bar rewrites data-theme; density is pinned dense (the
      // toggle was dropped — a workstation UI does not need the choice).
      data-theme="light"
      data-density="dense"
      className={`${sans.variable} ${mono.variable} ${serif.variable}`}
    >
      <body>
        {apiUrl && (
          <script
            dangerouslySetInnerHTML={{
              __html: `window.__ESTIMO_API__=${JSON.stringify(apiUrl).replace(/</g, "\\u003c")};`,
            }}
          />
        )}
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
