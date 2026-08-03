"use client";

/** Workspace: estimate list + BRD upload (UI-VISION §4.1, table-first). */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type EstimateSummary } from "@/lib/api";
import { detectLocale, setLocale, statusLabel, t, type Locale } from "@/lib/i18n";

const STATUS_COLOR: Record<string, string> = {
  awaiting_answers: "var(--crit)",
  ready_for_estimation: "var(--acc)",
  boe_draft: "var(--ok)",
};

export default function WorkspacePage() {
  const [locale, setLocaleState] = useState<Locale>("en");
  const [estimates, setEstimates] = useState<EstimateSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLocaleState(detectLocale());
  }, []);

  const refresh = useCallback(() => {
    api.listEstimates().then(setEstimates).catch((err) => setError(String(err)));
  }, []);
  useEffect(refresh, [refresh]);

  async function onUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    if (!input.files?.length) return;
    setUploading(true);
    setError(null);
    try {
      await api.upload(input.files[0]);
      refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      // Reset so re-selecting the same file after a failure fires change again.
      input.value = "";
      setUploading(false);
    }
  }

  function switchLocale(next: Locale) {
    setLocale(next);
    setLocaleState(next);
  }

  return (
    <main>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 16,
        }}
      >
        <div>
          <h1 style={{ margin: 0 }}>{t(locale, "appTitle")}</h1>
          <span className="muted">{t(locale, "tagline")}</span>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <Link href="/dashboard">{t(locale, "dashboard")}</Link>
          <select
            aria-label="Language"
            value={locale}
            onChange={(event) => switchLocale(event.target.value as Locale)}
          >
            <option value="en">EN</option>
            <option value="tr">TR</option>
          </select>
        </div>
      </header>

      <div className="card" style={{ marginBottom: 16 }}>
        <label>
          <strong>{t(locale, "upload")}</strong>{" "}
          <input type="file" accept=".docx" disabled={uploading} onChange={onUpload} />
        </label>
        {uploading && <span className="muted"> {t(locale, "uploading")}</span>}
        {error && (
          <p style={{ color: "var(--crit)" }} role="alert">
            {error}
          </p>
        )}
      </div>

      <h2>{t(locale, "estimates")}</h2>
      {estimates.length === 0 ? (
        <p className="muted">{t(locale, "noEstimates")}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>BRD</th>
              <th>{t(locale, "status")}</th>
              <th>{t(locale, "requirements")}</th>
              <th>{t(locale, "blocked")}</th>
              <th>{t(locale, "openQuestions")}</th>
              <th>{t(locale, "workItems")}</th>
            </tr>
          </thead>
          <tbody>
            {estimates.map((estimate) => (
              <tr key={estimate.id}>
                <td>
                  <Link href={`/estimates/${estimate.id}`}>
                    {estimate.brd_ref}
                  </Link>{" "}
                  <span className="muted">{estimate.title.slice(0, 60)}</span>
                </td>
                <td>
                  <span
                    className="chip"
                    style={{ color: STATUS_COLOR[estimate.status] ?? "var(--mut)" }}
                  >
                    {statusLabel(locale, estimate.status)}
                  </span>
                </td>
                <td>{estimate.requirements}</td>
                <td>{estimate.blocked}</td>
                <td>{estimate.open_questions}</td>
                <td>{estimate.work_items}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
