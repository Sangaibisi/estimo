"use client";

/** 9 · Knowledge Curation — "Candidate pages reviewed against their sources, then
 * published with a version."
 *
 * The design's argument is provenance: the queue on the left, the sources and the
 * distilled candidate side by side (serif = what the wiki says, sans = what we
 * distilled, only the candidate tinted), and the version stated on the chip, in the
 * primary button and in the footnote. */

import { useCallback, useEffect, useState } from "react";
import { api, type CanonicalEntry } from "@/lib/api";
import { t } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, StatusChip } from "@/components/ui";
import { IconKnowledge } from "@/components/icons";

export default function KnowledgePage() {
  const [pages, setPages] = useState<CanonicalEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [approver, setApprover] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .listCanonical()
      .then((entries) => {
        setPages(entries);
        setSelectedId((current) => current ?? entries[0]?.id ?? null);
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  const selected = pages.find((page) => page.id === selectedId) ?? null;
  const drafts = pages.filter((page) => page.status !== "approved").length;
  const published = pages.filter((page) => page.status === "approved").length;
  const drifted = pages.filter((page) => page.stale).length;

  return (
    <section className="scr">
      <div className="page-h">
        <IconKnowledge size={18} />
        <h2>{t("knowledge")}</h2>
        <span className="sub">{t("knowledgeSubtitle")}</span>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <BandHeader
          title={t("canonicalTitle")}
          right={
            <>
              <Chip>
                {t("queueWord")} {drafts}
              </Chip>
              {drifted > 0 && <StatusChip status="warn">{t("driftedWord")} {drifted}</StatusChip>}
              <Chip>
                {t("publishedWord")} {published}
              </Chip>
            </>
          }
        />

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

        <div style={{ display: "flex", minHeight: 460 }}>
          {/* Candidate queue */}
          <div
            style={{
              width: 266,
              flex: "none",
              borderRight: "1px solid var(--line)",
              background: "var(--surf2)",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)" }}>
              <Lbl>{t("candidateQueue")}</Lbl>
            </div>
            <div style={{ padding: 10, display: "flex", flexDirection: "column", gap: 8 }}>
              {pages.length === 0 && (
                <p style={{ fontSize: 12.5, color: "var(--ink2)", margin: 0 }}>
                  {t("noCandidates")}
                </p>
              )}
              {pages.map((page) => (
                <button
                  key={page.id}
                  type="button"
                  className="card"
                  onClick={() => setSelectedId(page.id)}
                  style={{
                    padding: "10px 12px",
                    textAlign: "left",
                    cursor: "pointer",
                    font: "inherit",
                    color: "inherit",
                    boxShadow:
                      page.id === selectedId ? "0 0 0 1px var(--acc) inset" : "var(--sh)",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: page.id === selectedId ? 500 : 400 }}>
                    {page.topic}
                  </div>
                  <div className="lbl" style={{ marginTop: 5 }}>
                    {page.status} · v{page.version}
                    {page.source_refs?.length ? ` · ${page.source_refs.length} src` : ""}
                  </div>
                  {page.stale && (
                    <div style={{ marginTop: 6 }}>
                      <StatusChip status="crit">{t("staleSource")}</StatusChip>
                    </div>
                  )}
                </button>
              ))}
            </div>
            <div
              style={{
                marginTop: "auto",
                borderTop: "1px solid var(--line)",
                padding: "12px 14px",
              }}
            >
              <Lbl>{t("newCandidate")}</Lbl>
              <input
                style={{ width: "100%", marginTop: 7 }}
                placeholder={t("canonicalTopic")}
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
              />
              <button
                type="button"
                className="btn"
                style={{ marginTop: 9 }}
                disabled={busy || !topic.trim()}
                onClick={() =>
                  run(async () => {
                    await api.createCanonical(topic.trim());
                    setTopic("");
                  })
                }
              >
                {t("generateCandidate")}
              </button>
            </div>
          </div>

          {/* Source | Candidate */}
          {selected ? (
            <div style={{ flex: 1, display: "flex", minWidth: 0 }}>
              <div
                style={{
                  flex: 1,
                  borderRight: "1px solid var(--line)",
                  padding: "14px 18px",
                  minWidth: 0,
                }}
              >
                <div
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
                >
                  <Lbl>
                    {t("sourceWord")} ·{" "}
                    {selected.source_refs?.length ?? 0} {t("pagesMerged")}
                  </Lbl>
                </div>
                <div
                  className="doc"
                  style={{
                    fontSize: 13,
                    lineHeight: 1.7,
                    color: "var(--ink2)",
                    marginTop: 12,
                  }}
                >
                  {(selected.source_refs ?? []).length === 0 ? (
                    <p style={{ margin: 0 }}>{t("noSources")}</p>
                  ) : (
                    (selected.source_refs ?? []).map((ref) => (
                      <p key={ref} style={{ margin: "0 0 10px" }}>
                        <Mn style={{ color: "var(--mut)" }}>{ref}</Mn>
                      </p>
                    ))
                  )}
                </div>
              </div>

              <div
                style={{
                  flex: 1,
                  padding: "14px 18px",
                  background: "var(--acc-bg)",
                  minWidth: 0,
                }}
              >
                <div
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
                >
                  <Lbl style={{ color: "var(--acc)" }}>{t("candidateDistilled")}</Lbl>
                  <Chip>
                    v{selected.version} {selected.status}
                  </Chip>
                </div>
                <p
                  style={{
                    fontSize: 13.5,
                    lineHeight: 1.65,
                    marginTop: 12,
                    color: "var(--ink)",
                    textWrap: "pretty",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {selected.body}
                </p>
                {selected.status !== "approved" && (
                  <div style={{ display: "flex", gap: 8, marginTop: 16, alignItems: "center" }}>
                    <input
                      placeholder={t("estimatorName")}
                      value={approver}
                      onChange={(event) => setApprover(event.target.value)}
                      style={{ width: 140 }}
                    />
                    <button
                      type="button"
                      className="btn p"
                      disabled={busy || !approver.trim()}
                      onClick={() =>
                        run(() => api.approveCanonical(selected.id, approver.trim()))
                      }
                    >
                      {t("approvePublish")} v{selected.version + 1}
                    </button>
                  </div>
                )}
                <div
                  style={{
                    fontSize: 11.5,
                    color: "var(--ink2)",
                    marginTop: 12,
                    textWrap: "pretty",
                  }}
                >
                  {t("versionFootnote")}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ flex: 1, padding: "26px 18px", color: "var(--mut)", fontSize: 13 }}>
              {t("selectCandidate")}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
