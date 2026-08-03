import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./tokens.css";

export const metadata: Metadata = {
  title: "Estimo",
  description: "Evidence-linked effort estimation",
};

// Rendered per request so ESTIMO_API_URL is read from the container environment at
// runtime — the browser-visible API origin must never be baked into the image
// (a build-time NEXT_PUBLIC_* bake breaks every deployment whose API host differs
// from the build host).
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: ReactNode }) {
  const apiUrl = process.env.ESTIMO_API_URL ?? "";
  return (
    <html lang="en">
      <body>
        {apiUrl && (
          <script
            dangerouslySetInnerHTML={{
              __html: `window.__ESTIMO_API__=${JSON.stringify(apiUrl).replace(/</g, "\\u003c")};`,
            }}
          />
        )}
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 16px" }}>
          {children}
        </div>
      </body>
    </html>
  );
}
