"use client";

/** 1 · Workspace — "Every estimate in flight — stage, open questions, and who is
 * waiting." Faithful to docs/design/estimo-ui.dc.html: header band, intake strip
 * with a drop zone and a live parse card, then the estimates .dt table. */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type EstimateSummary } from "@/lib/api";
import { statusLabel, t } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, StatusChip } from "@/components/ui";
import { IconEstimates } from "@/components/icons";

/** Stage of an estimate, 1..5 the way the design's row strip reads. Previously
 * has_boe mapped to 4, which made "1 Reading" and "5 BoE" unreachable and showed
 * every BoE-stage estimate one stage behind. */
function stageOf(estimate: EstimateSummary): number {
  if (estimate.has_boe) return 5;
  if (estimate.open_questions > 0) return 2;
  if (estimate.requirements === 0) return 1;
  if (estimate.work_items > 0) return 4;
  return 3;
}

const STAGE_KEYS = ["stgRead", "stgQ", "stgImpact", "stgEst", "stgBoe"] as const;

function RowStages({ at }: { at: number }) {
  // The design's labeled .stg pill strip at scale(.86) — done/on states carried by
  // the shared stage classes, not bespoke tick bars.
  return (
    <div
      style={{ display: "flex", transform: "scale(.86)", transformOrigin: "left center" }}
    >
      {STAGE_KEYS.map((key, index) => (
        <span
          key={key}
          className={`stg ${index + 1 < at ? "done" : index + 1 === at ? "on" : ""}`.trim()}
          style={{ cursor: "default" }}
        >
          {t(key)}
        </span>
      ))}
    </div>
  );
}

export default function WorkspacePage() {
  const [estimates, setEstimates] = useState<EstimateSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

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
      <div className="page-h">
        <IconEstimates size={18} />
        <h2>{t("estimates")}</h2>
        <span className="sub">{t("workspaceSubtitle")}</span>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <BandHeader
          title={t("estimates")}
          subtitle={`${estimates.length} ${t("inFlight")} · ${waiting} ${t("waitingCustomer")}`}
          right={
            <button
              type="button"
              className="btn p"
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
            >
              {t("newEstimate")}
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
            <span style={{ color: "var(--ink2)", fontSize: 13 }}>{t("dropBrd")}</span>
            <span>{t("orBrowse")}</span>
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
                  {t("firstRead")} — {uploadName}
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
                  {t("uploading")}
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
            {t("noEstimates")}
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <th style={{ width: 300 }}>{t("file")}</th>
                <th style={{ width: 240 }}>{t("stage")}</th>
                <th style={{ width: 74 }}>{t("items")}</th>
                <th style={{ width: 92 }}>{t("openQ")}</th>
                <th style={{ width: 92 }}>{t("blocked")}</th>
                <th>{t("waitingOn")}</th>
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
                      <RowStages at={stage} />
                    </td>
                    <td className="num">{estimate.work_items}</td>
                    <td>
                      {estimate.open_questions > 0 ? (
                        <StatusChip status="warn">{estimate.open_questions}</StatusChip>
                      ) : stage === 1 ? (
                        // Not read yet — there is nothing to count. A literal 0 is
                        // reserved for "the gate passed clean" below.
                        <Mn style={{ color: "var(--mut)" }}>—</Mn>
                      ) : (
                        <Mn style={{ color: "var(--mut)" }}>0</Mn>
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
                        t("waitingCustomer")
                      ) : (
                        <Chip tone={estimate.has_boe ? "acc" : "neutral"}>
                          {statusLabel(estimate.status)}
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
        <Lbl>{t("keyboardHint")}</Lbl>
      </div>
    </section>
  );
}
