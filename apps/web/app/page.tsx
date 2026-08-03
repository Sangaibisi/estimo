"use client";

/** 1 · Workspace — "Every estimate in flight — stage, open questions, and who is
 * waiting." Faithful to docs/design/estimo-ui.dc.html: header band, intake strip
 * with a drop zone and a live parse card, then the estimates .dt table. */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type EstimateSummary } from "@/lib/api";
import { detectLocale, statusLabel, t, type Locale } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, StatusChip } from "@/components/ui";

/** Stage of an estimate expressed the way the design's StageStrip reads. */
function stageOf(estimate: EstimateSummary): { index: number; label: string } {
  if (estimate.has_boe) return { index: 4, label: "4 Estimate" };
  if (estimate.open_questions > 0) return { index: 2, label: "2 Questions" };
  return { index: 3, label: "3 Impact" };
}

const STAGES = ["1 Reading", "2 Questions", "3 Impact", "4 Estimate", "5 BoE"];

function MiniStages({ at }: { at: number }) {
  // Row-level stage read-out: five ticks, filled up to the current stage. Shape and
  // position carry the state — not colour alone.
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {STAGES.map((label, index) => (
        <span
          key={label}
          title={label}
          style={{
            width: index + 1 === at ? 18 : 10,
            height: 4,
            borderRadius: 2,
            background:
              index + 1 < at
                ? "var(--line2)"
                : index + 1 === at
                  ? "var(--acc)"
                  : "var(--surf3)",
          }}
        />
      ))}
      <span className="mn" style={{ color: "var(--mut)", marginLeft: 6 }}>
        {STAGES[at - 1]}
      </span>
    </div>
  );
}

export default function WorkspacePage() {
  const [locale, setLocaleState] = useState<Locale>("en");
  const [estimates, setEstimates] = useState<EstimateSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => setLocaleState(detectLocale()), []);

  const refresh = useCallback(() => {
    api.listEstimates().then(setEstimates).catch((err) => setError(String(err)));
  }, []);
  useEffect(refresh, [refresh]);

  async function upload(file: File) {
    setUploading(true);
    setUploadName(file.name);
    setError(null);
    try {
      await api.upload(file);
      refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setUploading(false);
      setUploadName(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const waiting = estimates.filter((estimate) => estimate.open_questions > 0).length;

  return (
    <section className="scr">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 19, fontWeight: 600, letterSpacing: "-0.01em" }}>
          {t(locale, "estimates")}
        </h2>
        <span style={{ fontSize: 13, color: "var(--mut)" }}>
          {t(locale, "workspaceSubtitle")}
        </span>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <BandHeader
          title={t(locale, "estimates")}
          subtitle={`${estimates.length} ${t(locale, "inFlight")} · ${waiting} ${t(locale, "waitingCustomer")}`}
          right={
            <button
              type="button"
              className="btn p"
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
            >
              {t(locale, "newEstimate")}
            </button>
          }
        />

        {/* Intake strip */}
        <div
          style={{
            display: "flex",
            gap: 16,
            padding: "14px 18px",
            borderBottom: "1px solid var(--line)",
            background: "var(--surf2)",
          }}
        >
          <label
            className="ph"
            style={{
              flex: 1,
              minHeight: 74,
              flexDirection: "column",
              gap: 3,
              cursor: uploading ? "progress" : "pointer",
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              const file = event.dataTransfer.files?.[0];
              if (file) void upload(file);
            }}
          >
            <span style={{ color: "var(--ink2)", fontSize: 13 }}>{t(locale, "dropBrd")}</span>
            <span>{t(locale, "orBrowse")}</span>
            <input
              ref={fileInput}
              type="file"
              accept=".docx"
              disabled={uploading}
              style={{ display: "none" }}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
              }}
            />
          </label>

          {uploading && (
            <div
              className="card"
              style={{ width: 430, flex: "none", padding: "12px 14px", background: "var(--surf)" }}
            >
              <div
                style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}
              >
                <span style={{ fontSize: 13, fontWeight: 500 }}>
                  {t(locale, "firstRead")} — {uploadName}
                </span>
              </div>
              <div
                style={{
                  height: 6,
                  borderRadius: 3,
                  background: "var(--surf3)",
                  marginTop: 9,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: "60%",
                    height: "100%",
                    background: "var(--acc)",
                    animation: "none",
                  }}
                />
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 14,
                  marginTop: 9,
                  fontSize: 11.5,
                  color: "var(--mut)",
                }}
              >
                <span style={{ color: "var(--ink)", fontWeight: 500 }}>
                  {t(locale, "uploading")}
                </span>
              </div>
            </div>
          )}
        </div>

        {error && (
          <div
            role="alert"
            style={{
              padding: "10px 18px",
              borderBottom: "1px solid var(--line)",
              background: "var(--crit-bg)",
              color: "var(--crit)",
              fontSize: 12.5,
            }}
          >
            {error}
          </div>
        )}

        {estimates.length === 0 ? (
          <div style={{ padding: "26px 18px", color: "var(--mut)", fontSize: 13 }}>
            {t(locale, "noEstimates")}
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <th style={{ width: 300 }}>{t(locale, "file")}</th>
                <th style={{ width: 240 }}>{t(locale, "stage")}</th>
                <th style={{ width: 74 }}>{t(locale, "items")}</th>
                <th style={{ width: 92 }}>{t(locale, "openQ")}</th>
                <th style={{ width: 92 }}>{t(locale, "blocked")}</th>
                <th>{t(locale, "waitingOn")}</th>
              </tr>
            </thead>
            <tbody>
              {estimates.map((estimate) => {
                const stage = stageOf(estimate);
                return (
                  <tr key={estimate.id}>
                    <td>
                      <Link
                        href={`/estimates/${estimate.id}`}
                        style={{ fontWeight: 500, color: "var(--ink)" }}
                      >
                        {estimate.brd_ref}
                      </Link>
                      <div className="lbl" style={{ marginTop: 3, textTransform: "none", letterSpacing: 0 }}>
                        {estimate.title.slice(0, 64)}
                      </div>
                    </td>
                    <td>
                      <MiniStages at={stage.index} />
                    </td>
                    <td className="num">{estimate.work_items}</td>
                    <td>
                      {estimate.open_questions > 0 ? (
                        <StatusChip status="warn">{estimate.open_questions}</StatusChip>
                      ) : (
                        <Mn style={{ color: "var(--mut)" }}>—</Mn>
                      )}
                    </td>
                    <td>
                      {estimate.blocked > 0 ? (
                        <StatusChip status="crit">{estimate.blocked}</StatusChip>
                      ) : (
                        <Mn style={{ color: "var(--mut)" }}>—</Mn>
                      )}
                    </td>
                    <td style={{ color: "var(--ink2)", fontSize: 12.5 }}>
                      {estimate.open_questions > 0 ? (
                        t(locale, "waitingCustomer")
                      ) : (
                        <Chip tone={estimate.has_boe ? "acc" : "neutral"}>
                          {statusLabel(locale, estimate.status)}
                        </Chip>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ marginTop: 10 }}>
        <Lbl>{t(locale, "keyboardHint")}</Lbl>
      </div>
    </section>
  );
}
