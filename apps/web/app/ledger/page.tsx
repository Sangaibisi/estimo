"use client";

/** 7 · Ledger & Analog Search — "What similar work actually cost, and how far the
 * estimate was off." Search runs through the same Turkish hybrid retrieval the
 * estimator uses, so this screen and the draft agree by construction. */

import { useCallback, useEffect, useState } from "react";
import { api, type LedgerEntry } from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, Num, RangeBar, StatusChip } from "@/components/ui";
import { IconLedger } from "@/components/icons";

export default function LedgerPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [withActuals, setWithActuals] = useState(0);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((q: string) => {
    api
      .ledger(q)
      .then((result) => {
        setEntries(result.entries);
        setTotal(result.total);
        setWithActuals(result.with_actuals);
        setSearched(result.searched);
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    setLocale(detectLocale());
    load("");
  }, [load]);

  const max = Math.max(
    1,
    ...entries.flatMap((entry) => [entry.estimate.pessimistic ?? 0, entry.actual_effort ?? 0]),
  );

  return (
    <section className="scr">
      <div className="page-h">
        <IconLedger size={18} />
        <h2>{t(locale, "ledger")}</h2>
        <span className="sub">{t(locale, "ledgerSubtitle")}</span>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <BandHeader
          title={t(locale, "ledger")}
          subtitle={`${total} ${t(locale, "entriesWord")} · ${withActuals} ${t(locale, "withActuals")}`}
          right={
            <>
              <input
                style={{ width: 280 }}
                placeholder={t(locale, "analogSearchPlaceholder")}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") load(query);
                }}
              />
              <button type="button" className="btn p" onClick={() => load(query)}>
                {t(locale, "search")}
              </button>
              {searched && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setQuery("");
                    load("");
                  }}
                >
                  {t(locale, "clearSearch")}
                </button>
              )}
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
          </div>
        )}

        {/* AnalogCard grid — the design's card view of the top matches, with the
            actual-effort tick allowed to sit OUTSIDE the band (that is the finding). */}
        {searched && entries.length > 0 && (
          <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--line)" }}>
            <Lbl>
              {t(locale, "analogMatches")} · {Math.min(entries.length, 4)} /{" "}
              {total} {t(locale, "closedJobsSuffix")}
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
                const band =
                  entry.estimate.optimistic !== null &&
                  entry.estimate.likely !== null &&
                  entry.estimate.pessimistic !== null
                    ? {
                        optimistic: entry.estimate.optimistic,
                        likely: entry.estimate.likely,
                        pessimistic: entry.estimate.pessimistic,
                      }
                    : null;
                return (
                  <div key={entry.id} className="card" style={{ padding: "11px 13px" }}>
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
                      <Mn style={{ color: "var(--mut)", flex: "none" }}>{entry.brd_ref}</Mn>
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
                      {band && entry.actual_effort !== null ? (
                        entry.actual_effort > band.pessimistic ? (
                          <StatusChip status="crit">
                            {t(locale, "devAbove")}
                            {band.pessimistic > 0 &&
                              ` · +${Math.round(
                                ((entry.actual_effort - band.pessimistic) /
                                  band.pessimistic) *
                                  100,
                              )}%`}
                          </StatusChip>
                        ) : entry.actual_effort < band.optimistic ? (
                          <StatusChip status="warn">{t(locale, "devBelow")}</StatusChip>
                        ) : (
                          <StatusChip status="ok">{t(locale, "devWithin")}</StatusChip>
                        )
                      ) : null}
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
          <div style={{ padding: "26px 18px", color: "var(--mut)", fontSize: 13 }}>
            {t(locale, "ledgerEmpty")}
          </div>
        ) : (
          <table className="dt">
            <thead>
              <tr>
                {searched && <th style={{ width: 40 }}>#</th>}
                <th style={{ width: 300 }}>{t(locale, "lineItem")}</th>
                <th style={{ width: 150 }}>{t(locale, "modules")}</th>
                <th style={{ width: 210 }}>{t(locale, "estimateGiven")}</th>
                <th style={{ width: 110 }}>{t(locale, "actualEffort")}</th>
                <th style={{ width: 120 }}>{t(locale, "deviationLabel")}</th>
                <th style={{ width: 130 }}>{t(locale, "source")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, index) => {
                const band =
                  entry.estimate.optimistic !== null &&
                  entry.estimate.likely !== null &&
                  entry.estimate.pessimistic !== null
                    ? {
                        optimistic: entry.estimate.optimistic,
                        likely: entry.estimate.likely,
                        pessimistic: entry.estimate.pessimistic,
                      }
                    : null;
                return (
                  <tr key={entry.id}>
                    {searched && (
                      <td>
                        <Mn style={{ color: "var(--mut)" }}>{index + 1}</Mn>
                      </td>
                    )}
                    <td>
                      <div style={{ fontSize: 13 }}>{entry.item_title}</div>
                      <Mn style={{ color: "var(--mut)" }}>{entry.brd_ref}</Mn>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {entry.module_tags.slice(0, 2).map((module) => (
                          <Chip key={module}>{module}</Chip>
                        ))}
                      </div>
                    </td>
                    <td>
                      {band ? (
                        <RangeBar band={band} max={max} legend={false} />
                      ) : entry.estimate.single !== null ? (
                        <Num>{entry.estimate.single} pd</Num>
                      ) : (
                        <Mn style={{ color: "var(--mut)" }}>—</Mn>
                      )}
                    </td>
                    <td className="num">
                      {entry.actual_effort !== null ? `${entry.actual_effort} pd` : "—"}
                    </td>
                    <td>
                      {entry.scope_changed ? (
                        <StatusChip status="crit">{t(locale, "scopeChanged")}</StatusChip>
                      ) : entry.actual_effort !== null && band ? (
                        // DeviationBadge: graded against the RANGE, not the single
                        // likely value — an actual inside the band is a kept promise
                        // even when it misses "likely".
                        entry.actual_effort > band.pessimistic ? (
                          <StatusChip status="crit">
                            {t(locale, "devAbove")}
                            {band.pessimistic > 0 &&
                              ` · +${Math.round(
                                ((entry.actual_effort - band.pessimistic) / band.pessimistic) * 100,
                              )}%`}
                          </StatusChip>
                        ) : entry.actual_effort < band.optimistic ? (
                          <StatusChip status="warn">{t(locale, "devBelow")}</StatusChip>
                        ) : (
                          <StatusChip status="ok">{t(locale, "devWithin")}</StatusChip>
                        )
                      ) : entry.deviation !== null ? (
                        <Chip
                          tone={
                            entry.deviation > 1.5 || entry.deviation < 0.66 ? "crit" : "neutral"
                          }
                        >
                          ×{entry.deviation}
                        </Chip>
                      ) : (
                        <Mn style={{ color: "var(--mut)" }}>—</Mn>
                      )}
                    </td>
                    <td>
                      <Chip tone={entry.origin === "product" ? "acc" : "neutral"}>
                        {entry.actual_source ?? entry.origin}
                      </Chip>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ marginTop: 10 }}>
        <Lbl>{t(locale, "ledgerFootnote")}</Lbl>
      </div>
    </section>
  );
}
