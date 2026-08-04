"use client";

/** 7 · Ledger & Analog Search — "What similar work actually cost, and how far the
 * estimate was off." Search runs through the same Turkish hybrid retrieval the
 * estimator uses, so this screen and the draft agree by construction.
 *
 * Two numbers on this screen are load-bearing and easy to fake:
 * - the **similarity** chip, which is rendered ONLY from a measured cosine distance
 *   (`entry.similarity`); when the dense leg did not run the screen says so instead
 *   of turning a rank into a percentage;
 * - the **"N of M closed jobs"** band, which counts the same slice the list shows. */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type ImportPreview,
  type ImportReport,
  type LedgerEntry,
  type LedgerPage,
} from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";
import {
  BandHeader,
  Chip,
  Lbl,
  Mn,
  Num,
  RangeBar,
  StatusChip,
} from "@/components/ui";
import { IconImport, IconLedger } from "@/components/icons";

type Band = { optimistic: number; likely: number; pessimistic: number };

function bandOf(entry: LedgerEntry): Band | null {
  const { optimistic, likely, pessimistic } = entry.estimate;
  return optimistic !== null && likely !== null && pessimistic !== null
    ? { optimistic, likely, pessimistic }
    : null;
}

/** Deviation graded against the RANGE, not the single likely value — an actual
 * inside the band is a kept promise even when it misses "likely". */
function DeviationBadge({
  entry,
  locale,
}: {
  entry: LedgerEntry;
  locale: Locale;
}) {
  const band = bandOf(entry);
  if (entry.actual_effort === null || !band) return null;
  if (entry.actual_effort > band.pessimistic) {
    return (
      <StatusChip status="crit">
        {t(locale, "devAbove")}
        {band.pessimistic > 0 &&
          ` · +${Math.round(
            ((entry.actual_effort - band.pessimistic) / band.pessimistic) * 100,
          )}%`}
      </StatusChip>
    );
  }
  if (entry.actual_effort < band.optimistic) {
    return <StatusChip status="warn">{t(locale, "devBelow")}</StatusChip>;
  }
  return <StatusChip status="ok">{t(locale, "devWithin")}</StatusChip>;
}

/** Month + year, in the reader's locale — a full date implies a precision the
 * ledger does not have about when work landed. */
function delivered(iso: string | null, locale: Locale): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(locale === "tr" ? "tr-TR" : "en-GB", {
    month: "short",
    year: "numeric",
  });
}

export default function LedgerPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [query, setQuery] = useState("");
  const [team, setTeam] = useState("");
  const [domain, setDomain] = useState("");
  const [page, setPage] = useState<LedgerPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  // Which request the rendered page belongs to. Without it a slow first response can
  // land after a fast second one and leave the previous slice's rows — and their
  // similarity chips — sitting under the newly-selected filters, which reads as data
  // about the slice you just chose. A failure has to clear the stale page for the
  // same reason: rows that no longer describe the controls above them are worse than
  // no rows.
  const request = useRef(0);

  const load = useCallback(
    (q: string, slice: { team: string; domain: string }) => {
      const ticket = ++request.current;
      api
        .ledger(q, { team: slice.team, domain: slice.domain })
        .then((result) => {
          if (ticket !== request.current) return;
          setPage(result);
          setError(null);
        })
        .catch((err) => {
          if (ticket !== request.current) return;
          setPage(null);
          setError(String(err));
        });
    },
    [],
  );

  useEffect(() => {
    setLocale(detectLocale());
    load("", { team: "", domain: "" });
  }, [load]);

  const entries = page?.entries ?? [];
  const searched = page?.searched ?? false;
  const facets = page?.facets ?? { teams: [], domains: [] };
  const max = Math.max(
    1,
    ...entries.flatMap((entry) => [
      entry.estimate.pessimistic ?? 0,
      entry.actual_effort ?? 0,
    ]),
  );

  const applySlice = (next: { team?: string; domain?: string }) => {
    const slice = { team: next.team ?? team, domain: next.domain ?? domain };
    setTeam(slice.team);
    setDomain(slice.domain);
    load(query, slice);
  };

  return (
    <section className="scr">
      <div className="page-h">
        <IconLedger size={18} />
        <h2>{t(locale, "ledger")}</h2>
        <span className="sub">{t(locale, "ledgerSubtitle")}</span>
      </div>

      {/* While the wizard is open the page makes room for it rather than letting the
          drawer sit on top of the rightmost columns — a covered column reads as a
          missing one. */}
      <div
        style={{
          paddingRight: importing ? 344 : 0,
          transition: "padding-right 120ms",
        }}
      >
        <div className="card" style={{ overflow: "hidden" }}>
          <BandHeader
            title={t(locale, "ledger")}
            subtitle={`${page?.total ?? 0} ${t(locale, "entriesWord")} · ${
              page?.with_actuals ?? 0
            } ${t(locale, "withActuals")}`}
            right={
              <>
                <input
                  style={{ width: 220 }}
                  placeholder={t(locale, "analogSearchPlaceholder")}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") load(query, { team, domain });
                  }}
                />
                <select
                  aria-label={t(locale, "teamWord")}
                  value={team}
                  onChange={(event) => applySlice({ team: event.target.value })}
                >
                  <option value="">{t(locale, "allTeams")}</option>
                  {facets.teams.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <select
                  aria-label={t(locale, "domainWord")}
                  value={domain}
                  onChange={(event) =>
                    applySlice({ domain: event.target.value })
                  }
                >
                  <option value="">{t(locale, "allDomains")}</option>
                  {facets.domains.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn p"
                  onClick={() => load(query, { team, domain })}
                >
                  {t(locale, "search")}
                </button>
                {(searched || team || domain) && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setQuery("");
                      setTeam("");
                      setDomain("");
                      load("", { team: "", domain: "" });
                    }}
                  >
                    {t(locale, "clearSearch")}
                  </button>
                )}
                <button
                  type="button"
                  className="btn"
                  onClick={() => setImporting(true)}
                >
                  <IconImport
                    size={14}
                    style={{ marginRight: 5, verticalAlign: -2 }}
                  />
                  {t(locale, "importSeedSet")}
                </button>
              </>
            }
          />

          {searched && (
            <div
              style={{
                padding: "10px 18px",
                borderBottom: "1px solid var(--line)",
                background: "var(--surf2)",
                fontSize: 12.5,
                color: "var(--ink2)",
              }}
            >
              {t(locale, "analogRankHint")}
              {/* Said whenever NO percentage could be shown — the dense leg being
                  off is only one of the two reasons; unembedded rows are the other,
                  and a reader owed an explanation does not care which. */}
              {entries.length > 0 &&
                entries.every((entry) => entry.similarity === null) &&
                ` · ${t(locale, "lexicalOnlyHint")}`}
            </div>
          )}

          {/* AnalogCard grid — the design's card view of the top matches, with the
              actual-effort tick allowed to sit OUTSIDE the band (that is the finding). */}
          {searched && entries.length > 0 && (
            <div
              style={{
                padding: "14px 18px",
                borderBottom: "1px solid var(--line)",
              }}
            >
              {/* "Closed" means an actual landed. `total` counts every row in the
                  slice — including the estimate-only rows connectors and seed
                  imports write — so using it here would call open work closed. */}
              <Lbl>
                {t(locale, "analogMatches")} · {Math.min(entries.length, 4)} /{" "}
                {page?.with_actuals ?? 0} {t(locale, "closedJobsSuffix")}
              </Lbl>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: 12,
                  marginTop: 10,
                }}
              >
                {entries.slice(0, 4).map((entry) => {
                  const band = bandOf(entry);
                  return (
                    <div
                      key={entry.id}
                      className="card"
                      style={{ padding: "11px 13px" }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          gap: 8,
                          alignItems: "baseline",
                        }}
                      >
                        <span style={{ fontSize: 13, fontWeight: 500 }}>
                          {entry.item_title}
                        </span>
                        {/* Only ever a MEASURED similarity. Null (lexical-only
                            retrieval) shows the ref instead of a made-up number. */}
                        {entry.similarity !== null ? (
                          <Chip
                            style={{ color: "var(--ev-analog)", flex: "none" }}
                            title={entry.brd_ref}
                          >
                            {Math.round(entry.similarity * 100)}%{" "}
                            {t(locale, "similarityWord")}
                          </Chip>
                        ) : (
                          <Mn style={{ color: "var(--mut)", flex: "none" }}>
                            {entry.brd_ref}
                          </Mn>
                        )}
                      </div>
                      <div style={{ marginTop: 9 }}>
                        {band ? (
                          <RangeBar
                            band={band}
                            max={max}
                            legend={false}
                            actual={entry.actual_effort}
                          />
                        ) : (
                          <Mn style={{ color: "var(--mut)" }}>—</Mn>
                        )}
                      </div>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginTop: 8,
                          fontSize: 12,
                          color: "var(--ink2)",
                        }}
                      >
                        <span className="mn">
                          {band
                            ? `${band.optimistic}–${band.pessimistic} pd ${t(locale, "estimatedWord")}`
                            : "—"}
                          {entry.actual_effort !== null &&
                            ` · ${entry.actual_effort} pd ${t(locale, "actualWord")}`}
                        </span>
                        <DeviationBadge entry={entry} locale={locale} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              style={{
                padding: "10px 18px",
                background: "var(--crit-bg)",
                color: "var(--crit)",
                fontSize: 12.5,
              }}
            >
              {error}
            </div>
          )}

          {entries.length === 0 ? (
            <div
              style={{
                padding: "26px 18px",
                color: "var(--mut)",
                fontSize: 13,
              }}
            >
              {/* A filter that matches nothing is not an empty ledger. Telling an
                  operator with 200 rows that theirs is empty sends them to import
                  data they already have. */}
              {searched || page?.sliced
                ? t(locale, "noMatchHere")
                : t(locale, "ledgerEmpty")}
            </div>
          ) : (
            /* The table's column widths are fixed; when the import drawer narrows the
               page, scroll rather than clip — a cut-off column reads as a missing one. */
            <div style={{ overflowX: "auto" }}>
              <table className="dt">
                <thead>
                  <tr>
                    {searched && <th style={{ width: 40 }}>#</th>}
                    <th style={{ width: 260 }}>{t(locale, "lineItem")}</th>
                    <th style={{ width: 90 }}>{t(locale, "deliveredWord")}</th>
                    <th style={{ width: 190 }}>{t(locale, "rangeThatDay")}</th>
                    <th style={{ width: 90 }}>{t(locale, "actualEffort")}</th>
                    <th style={{ width: 120 }}>
                      {t(locale, "deviationLabel")}
                    </th>
                    <th style={{ width: 110 }}>{t(locale, "teamWord")}</th>
                    <th style={{ width: 90 }}>{t(locale, "boeRowColumn")}</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry, index) => {
                    const band = bandOf(entry);
                    return (
                      <tr key={entry.id}>
                        {searched && (
                          <td>
                            <Mn style={{ color: "var(--mut)" }}>{index + 1}</Mn>
                          </td>
                        )}
                        <td>
                          <div style={{ fontSize: 13 }}>{entry.item_title}</div>
                          <Mn style={{ color: "var(--mut)" }}>
                            {entry.brd_ref}
                          </Mn>
                          <div
                            style={{
                              display: "flex",
                              gap: 4,
                              flexWrap: "wrap",
                              marginTop: 4,
                            }}
                          >
                            {entry.module_tags.slice(0, 2).map((module) => (
                              <Chip key={module}>{module}</Chip>
                            ))}
                          </div>
                        </td>
                        <td>
                          <Mn style={{ color: "var(--ink2)" }}>
                            {delivered(entry.completed_at, locale)}
                          </Mn>
                        </td>
                        <td>
                          {/* "Range that day" — the band as it was GIVEN, which is what
                            a deviation is measured against. */}
                          {band ? (
                            <RangeBar band={band} max={max} legend={false} />
                          ) : entry.estimate.single !== null ? (
                            <Num>{entry.estimate.single} pd</Num>
                          ) : (
                            <Mn style={{ color: "var(--mut)" }}>—</Mn>
                          )}
                        </td>
                        <td className="num">
                          {entry.actual_effort !== null
                            ? `${entry.actual_effort} pd`
                            : "—"}
                        </td>
                        <td>
                          {entry.scope_changed ? (
                            <StatusChip status="crit">
                              {t(locale, "scopeChanged")}
                            </StatusChip>
                          ) : entry.actual_effort !== null && band ? (
                            <DeviationBadge entry={entry} locale={locale} />
                          ) : entry.deviation !== null ? (
                            <Chip
                              tone={
                                entry.deviation > 1.5 || entry.deviation < 0.66
                                  ? "crit"
                                  : "neutral"
                              }
                            >
                              ×{entry.deviation}
                            </Chip>
                          ) : (
                            <Mn style={{ color: "var(--mut)" }}>—</Mn>
                          )}
                        </td>
                        <td>
                          {entry.team ? (
                            <Chip>{entry.team}</Chip>
                          ) : (
                            <Mn style={{ color: "var(--mut)" }}>—</Mn>
                          )}
                        </td>
                        <td>
                          {/* Only product-written rows have a source row to open. */}
                          {entry.boe_link ? (
                            <a
                              className="mn"
                              href={`/estimates/${entry.boe_link.estimate_id}`}
                              style={{ color: "var(--acc)" }}
                            >
                              {t(locale, "openWord")} →
                            </a>
                          ) : (
                            <Chip>{entry.actual_source ?? entry.origin}</Chip>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {importing && (
          <ImportWizard
            locale={locale}
            onClose={() => setImporting(false)}
            onImported={() => load(query, { team, domain })}
          />
        )}
      </div>

      <div style={{ marginTop: 10 }}>
        <Lbl>{t(locale, "ledgerFootnote")}</Lbl>
      </div>
    </section>
  );
}

/** The seed-set import wizard (design screen 7, right panel).
 *
 * Four steps, in the order the design argues for: choose the file, map its columns,
 * confirm what must be true before anything enters, then read the report — including
 * the rows that did NOT enter. The mapping is the whole contract (the server applies
 * no alias fallback underneath it) and the checklist is enforced server-side, so
 * neither step is decoration. */
function ImportWizard({
  locale,
  onClose,
  onImported,
}: {
  locale: Locale;
  onClose: () => void;
  onImported: () => void;
}) {
  const [step, setStep] = useState(1);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [checks, setChecks] = useState({ personal: false, anonymised: false });
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFailed, setShowFailed] = useState(false);

  const choose = async (picked: File) => {
    setFile(picked);
    setBusy(true);
    setError(null);
    try {
      const result = await api.previewImport(picked);
      setPreview(result);
      setMapping(
        Object.fromEntries(result.columns.map((c) => [c.header, c.field])),
      );
      setStep(2);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await api.runImport(file, mapping));
      setStep(4);
      onImported();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const mapped = new Set(Object.values(mapping).filter(Boolean) as string[]);
  const missing = ["brd_ref", "item_title"].filter(
    (field) => !mapped.has(field),
  );

  return (
    <div
      className="card"
      /* A drawer, not a grid column: at real viewport widths a 320px column squeezes
         the table it exists to add rows to. */
      style={{
        padding: "13px 15px",
        position: "fixed",
        top: 78,
        right: 18,
        width: 320,
        maxHeight: "calc(100vh - 96px)",
        overflowY: "auto",
        zIndex: 20,
        boxShadow: "0 8px 28px rgba(16, 32, 56, 0.16)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600 }}>
          {t(locale, "seedImportTitle")}
        </div>
        <Lbl>{t(locale, "stepOf").replace("{n}", String(step))}</Lbl>
      </div>
      <div style={{ display: "flex", gap: 3, marginTop: 9 }}>
        {[1, 2, 3, 4].map((n) => (
          <div
            key={n}
            style={{
              height: 3,
              flex: 1,
              borderRadius: 2,
              background: n <= step ? "var(--acc)" : "var(--line2)",
            }}
          />
        ))}
      </div>

      {error && (
        <div
          role="alert"
          style={{
            marginTop: 10,
            padding: "8px 10px",
            background: "var(--crit-bg)",
            color: "var(--crit)",
            fontSize: 12,
            borderRadius: 6,
          }}
        >
          {error}
        </div>
      )}

      {step === 1 && (
        <div style={{ marginTop: 11 }}>
          <Lbl>{t(locale, "chooseFile")}</Lbl>
          <input
            type="file"
            accept=".csv,.xlsx,.xlsm"
            style={{ marginTop: 8, width: "100%" }}
            disabled={busy}
            onChange={(event) => {
              const picked = event.target.files?.[0];
              if (picked) void choose(picked);
            }}
          />
        </div>
      )}

      {step === 2 && preview && (
        <div style={{ marginTop: 11 }}>
          <Lbl>{t(locale, "mapTheColumns")}</Lbl>
          <div style={{ marginTop: 8, maxHeight: 300, overflowY: "auto" }}>
            {preview.columns.map((column) => (
              <div
                key={column.header}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 8,
                  padding: "7px 0",
                  borderTop: "1px solid var(--line)",
                  fontSize: 12.5,
                }}
              >
                <span style={{ minWidth: 0 }}>
                  <span className="mn" style={{ color: "var(--mut)" }}>
                    {column.header}
                  </span>
                  {column.sample && (
                    <div style={{ color: "var(--mut)", fontSize: 11 }}>
                      {column.sample}
                    </div>
                  )}
                </span>
                <select
                  aria-label={column.header}
                  value={mapping[column.header] ?? ""}
                  onChange={(event) =>
                    setMapping((current) => ({
                      ...current,
                      [column.header]: event.target.value || null,
                    }))
                  }
                  style={{ maxWidth: 150 }}
                >
                  <option value="">{t(locale, "doNotImport")}</option>
                  {preview.fields.map((field) => (
                    <option key={field} value={field}>
                      {field}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          {missing.length > 0 && (
            <div style={{ marginTop: 9, fontSize: 12, color: "var(--crit)" }}>
              {t(locale, "missingRequired").replace(
                "{fields}",
                missing.join(", "),
              )}
            </div>
          )}
          <div style={{ display: "flex", gap: 6, marginTop: 11 }}>
            <button type="button" className="btn" onClick={() => setStep(1)}>
              {t(locale, "backWord")}
            </button>
            <button
              type="button"
              className="btn p"
              disabled={missing.length > 0}
              onClick={() => setStep(3)}
            >
              {t(locale, "nextWord")}
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div style={{ marginTop: 11 }}>
          <Lbl>{t(locale, "beforeAnythingEnters")}</Lbl>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              marginTop: 9,
            }}
          >
            <label
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                fontSize: 12.5,
              }}
            >
              <input
                type="checkbox"
                checked={checks.personal}
                onChange={(event) =>
                  setChecks((c) => ({ ...c, personal: event.target.checked }))
                }
              />
              {t(locale, "checkNoPersonalData")}
            </label>
            <label
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                fontSize: 12.5,
              }}
            >
              <input
                type="checkbox"
                checked={checks.anonymised}
                onChange={(event) =>
                  setChecks((c) => ({ ...c, anonymised: event.target.checked }))
                }
              />
              {t(locale, "checkCustomersAnonymised")}
            </label>
          </div>
          <div style={{ marginTop: 9, fontSize: 11.5, color: "var(--mut)" }}>
            {t(locale, "checklistBlocks")}
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 11 }}>
            <button type="button" className="btn" onClick={() => setStep(2)}>
              {t(locale, "backWord")}
            </button>
            <button
              type="button"
              className="btn p"
              disabled={busy || !checks.personal || !checks.anonymised}
              onClick={() => void run()}
            >
              {busy ? t(locale, "importingWord") : t(locale, "startImport")}
            </button>
          </div>
        </div>
      )}

      {step === 4 && report && (
        <div style={{ marginTop: 11, fontSize: 12.5 }}>
          <div>
            {t(locale, "importDone")
              .replace("{imported}", String(report.imported))
              .replace("{total}", String(report.total_rows))}
          </div>
          {report.rejected.length > 0 && (
            <div
              className="card"
              style={{
                padding: "9px 11px",
                marginTop: 10,
                borderColor: "var(--crit)",
                background: "var(--crit-bg)",
              }}
            >
              <div style={{ color: "var(--ink)" }}>
                {t(locale, "failedRowsQueue").replace(
                  "{n}",
                  String(report.rejected.length),
                )}
              </div>
              <button
                type="button"
                className="btn"
                style={{ marginTop: 8 }}
                onClick={() => setShowFailed((open) => !open)}
              >
                {t(locale, "reviewFailedRows")}
              </button>
              {showFailed && (
                <div
                  style={{ marginTop: 8, maxHeight: 200, overflowY: "auto" }}
                >
                  {report.rejected.map((row) => (
                    <div
                      key={row.row}
                      style={{ padding: "5px 0", fontSize: 11.5 }}
                    >
                      <span className="mn" style={{ color: "var(--mut)" }}>
                        {t(locale, "rowWord")} {row.row}
                      </span>
                      <div>{row.error}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {report.duplicates.length > 0 && (
            <div style={{ marginTop: 10, color: "var(--ink2)" }}>
              {t(locale, "duplicatesNote").replace(
                "{n}",
                String(report.duplicates.length),
              )}
            </div>
          )}
          {/* Parse warnings are the no-silent-loss half of the report: a cell that
              held a real but unreadable value ("12 adam/gün", "March 2024") imports
              as if the field were empty. Not showing them presents a row that lost
              its actual as a row that never had one. */}
          {report.warnings.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Lbl>{t(locale, "parseWarnings")}</Lbl>
              <div style={{ marginTop: 6, maxHeight: 160, overflowY: "auto" }}>
                {report.warnings.map((row) => (
                  <div
                    key={`${row.row}-${row.warning}`}
                    style={{ padding: "4px 0", fontSize: 11.5 }}
                  >
                    <span className="mn" style={{ color: "var(--mut)" }}>
                      {t(locale, "rowWord")} {row.row}
                    </span>
                    <div>{row.warning}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {report.without_actuals > 0 && (
            <div style={{ marginTop: 10, color: "var(--ink2)" }}>
              {t(locale, "noActualsNote").replace(
                "{n}",
                String(report.without_actuals),
              )}
            </div>
          )}
          {Object.keys(report.unknown_modules).length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Lbl>{t(locale, "reviewQueueModules")}</Lbl>
              <div
                style={{
                  display: "flex",
                  gap: 4,
                  flexWrap: "wrap",
                  marginTop: 6,
                }}
              >
                {Object.entries(report.unknown_modules).map(
                  ([module, count]) => (
                    <Chip key={module} tone="warn">
                      {module} ×{count}
                    </Chip>
                  ),
                )}
              </div>
            </div>
          )}
          <div style={{ display: "flex", gap: 6, marginTop: 11 }}>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setStep(1);
                setFile(null);
                setPreview(null);
                setReport(null);
                setChecks({ personal: false, anonymised: false });
              }}
            >
              {t(locale, "startOver")}
            </button>
            <button type="button" className="btn" onClick={onClose}>
              {t(locale, "cancelWord")}
            </button>
          </div>
        </div>
      )}

      {step < 4 && (
        <button
          type="button"
          className="btn"
          style={{ marginTop: 11 }}
          onClick={onClose}
        >
          {t(locale, "cancelWord")}
        </button>
      )}
    </div>
  );
}
