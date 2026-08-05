"use client";

/** Settings — deployment configuration only: connections + the model gateway.
 *
 * The 2026-08 redesign cut this surface down to what an operator actually
 * configures (the admin JSON: gateway + connections). Runtime/auth facts became
 * a one-line system strip — reported, never edited (env-only) — and the static
 * roles explainer left entirely. Credentials entered here are sealed before
 * storage (ADR-0008) and never serialized back; the env-var-name lane remains.
 * The Model gateway card EDITS runtime config: saving overrides the environment
 * immediately. */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type ConnectionEntry,
  type GatewayCheckResult,
  type SystemInfo,
} from "@/lib/api";
import { DATE_LOCALE, t } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, StatusChip } from "@/components/ui";
import { CONNECTOR_LABELS, ConnectorMark, IconAdmin } from "@/components/icons";
import { AccountsAdmin, SetupCard } from "@/components/AccountsAdmin";

const KINDS = ["confluence", "bitbucket", "github", "gitlab", "git", "jira"];

/** Per-kind hint for the free-form config JSON — the shapes the connectors read. */
const CONFIG_HINTS: Record<string, string> = {
  confluence: '{"space_keys": ["AUR"], "email": "…"}',
  bitbucket: '{"auth": "bearer", "username": "…", "branch": "main"}',
  github: '{"branch": "main"}',
  gitlab: '{"branch": "main"}',
  git: '{"branch": "main"}',
  jira: '{"email": "…", "jql": "project = AUR", "points_to_pd": 1}',
};

function statsLine(stats: Record<string, unknown> | null): string {
  if (!stats) return "";
  const graph = stats.graph as Record<string, unknown> | undefined;
  if (graph && typeof graph === "object") {
    const n = (v: unknown) => (typeof v === "number" ? v.toLocaleString(DATE_LOCALE) : "—");
    return `${n(graph.files)} files · ${n(graph.modules)} modules · ${n(graph.symbols)} symbols`;
  }
  return Object.entries(stats)
    .filter(([, value]) => typeof value === "number" || typeof value === "string")
    .slice(0, 4)
    .map(([key, value]) => `${value} ${key}`)
    .join(" · ");
}

export default function AdminPage() {
  const [connections, setConnections] = useState<ConnectionEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [gatewayResult, setGatewayResult] = useState<GatewayCheckResult | null>(null);
  const [checking, setChecking] = useState(false);

  const [kind, setKind] = useState("bitbucket");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [configText, setConfigText] = useState("{}");
  const [secretValue, setSecretValue] = useState("");
  const [secretEnv, setSecretEnv] = useState("");
  const [aclKeys, setAclKeys] = useState("");
  const [cadenceEdit, setCadenceEdit] = useState<Record<string, string>>({});
  const [pinRef, setPinRef] = useState<Record<string, string>>({});
  const [pinNote, setPinNote] = useState<Record<string, string>>({});

  // Model gateway form (ADR-0008): initialized from /v1/system, saved via PUT.
  const [gwBaseUrl, setGwBaseUrl] = useState("");
  const [gwApiKey, setGwApiKey] = useState("");
  const [gwTimeout, setGwTimeout] = useState("");
  const [gwConnectTimeout, setGwConnectTimeout] = useState("");
  const [gwRetries, setGwRetries] = useState("");
  const [gwProfiles, setGwProfiles] = useState<{ stage: string; profile: string }[]>([]);
  const [gwSaved, setGwSaved] = useState(false);

  const loadSystem = useCallback(() => {
    api
      .systemInfo()
      .then((info) => {
        setSystem(info);
        // An unconfigured deployment leaves the form EMPTY rather than
        // pre-filling invented defaults — the operator is typing their endpoint
        // for the first time, not correcting ours.
        setGwBaseUrl(info.gateway.base_url ?? "");
        setGwTimeout(
          info.gateway.timeout_seconds === null ? "" : String(info.gateway.timeout_seconds),
        );
        setGwConnectTimeout(
          info.gateway.connect_timeout_seconds === null
            ? ""
            : String(info.gateway.connect_timeout_seconds),
        );
        setGwRetries(info.gateway.max_retries === null ? "" : String(info.gateway.max_retries));
        setGwProfiles(
          Object.entries(info.gateway.profiles).map(([stage, profile]) => ({ stage, profile })),
        );
        setGwApiKey("");
      })
      .catch((err) => setError(String(err)));
  }, []);

  const refresh = useCallback(() => {
    api
      .listConnections()
      .then(setConnections)
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    refresh();
    loadSystem();
  }, [refresh, loadSystem]);

  async function checkGateway() {
    setChecking(true);
    setGatewayResult(null);
    try {
      setGatewayResult(await api.gatewayCheck());
    } catch (err) {
      setGatewayResult({ ok: false, latency_ms: 0, error: String(err) });
    } finally {
      setChecking(false);
    }
  }

  /** Numeric field: empty means "leave it alone"; a non-number is a hard error,
   * because silently dropping it would show "saved" while reverting the field. */
  function numeric(raw: string, label: string): number | null {
    if (!raw.trim()) return null;
    const value = Number(raw.trim().replace(",", "."));
    if (!Number.isFinite(value)) throw new Error(`${label}: not a number — "${raw}"`);
    return value;
  }

  async function saveGateway(reset: boolean) {
    setBusy(true);
    setError(null);
    setGwSaved(false);
    try {
      if (reset) {
        await api.putGateway({ reset: true });
      } else {
        const rows = gwProfiles.map((row) => ({
          stage: row.stage.trim(),
          profile: row.profile.trim(),
        }));
        // Half-filled and duplicate rows would vanish silently in an object
        // literal (last-wins), so they are refused rather than swallowed.
        const halfFilled = rows.find((row) => !row.stage !== !row.profile);
        if (halfFilled) {
          throw new Error(
            `profile row incomplete: "${halfFilled.stage || "?"}" → "${halfFilled.profile || "?"}"`,
          );
        }
        const filled = rows.filter((row) => row.stage && row.profile);
        const duplicate = filled.find(
          (row, index) => filled.findIndex((other) => other.stage === row.stage) !== index,
        );
        if (duplicate) throw new Error(`duplicate stage: "${duplicate.stage}"`);

        const timeout = numeric(gwTimeout, t("timeoutShort"));
        const connectTimeout = numeric(gwConnectTimeout, t("timeoutShort"));
        const retries = numeric(gwRetries, t("retriesShort"));

        await api.putGateway({
          // Only send the URL when the operator actually changed it: the value in
          // the field came from /v1/system with userinfo STRIPPED, so echoing it
          // back would persist a redacted (broken) URL over a working one.
          ...(gwBaseUrl.trim() !== (system?.gateway.base_url ?? "")
            ? { base_url: gwBaseUrl.trim() }
            : {}),
          ...(gwApiKey ? { api_key: gwApiKey } : {}),
          profiles: Object.fromEntries(filled.map((row) => [row.stage, row.profile])),
          ...(timeout !== null ? { timeout_seconds: timeout } : {}),
          ...(connectTimeout !== null ? { connect_timeout_seconds: connectTimeout } : {}),
          ...(retries !== null ? { max_retries: retries } : {}),
        });
      }
      setGwSaved(!reset);
      loadSystem();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

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

  let configValid = true;
  try {
    JSON.parse(configText || "{}");
  } catch {
    configValid = false;
  }

  return (
    <section className="scr" style={{ maxWidth: 1120 }}>
      <div className="page-h">
        <IconAdmin size={18} />
        <h2>Settings</h2>
        <span className="sub">Deployment configuration — connections and the model gateway.</span>
      </div>

      {error && (
        <div
          role="alert"
          style={{
            padding: "10px 16px",
            marginBottom: 14,
            border: "1px solid var(--crit)",
            borderRadius: "var(--r)",
            background: "var(--crit-bg)",
            color: "var(--crit)",
            fontSize: 12.5,
          }}
        >
          {error}
        </div>
      )}

      {/* Shown once in a deployment's life, while anyone can still reach the API. */}
      <SetupCard />

      {/* ---- Workspaces & people (platform admin only) ---- */}
      <AccountsAdmin />

      {/* ---- Connections ---- */}
      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title={t("connections")}
          subtitle="Synced sources — they appear on the repository map and feed retrieval."
          right={
            <button type="button" className="btn glow" onClick={() => setShowForm(!showForm)}>
              {showForm ? "Close" : `+ ${t("addConnection")}`}
            </button>
          }
        />

        {showForm && (
          <div
            style={{
              padding: "16px 18px",
              borderBottom: "1px solid var(--line)",
              background: "oklch(0.19 0.016 300)",
            }}
          >
            <div
              style={{
                fontSize: 12,
                color: "var(--ink2)",
                marginBottom: 12,
                textWrap: "pretty",
              }}
            >
              {t("secretEnvHint")}
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "150px 1fr 1fr",
                gap: 8,
                alignItems: "center",
              }}
            >
              <select aria-label="kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                {KINDS.map((option) => (
                  <option key={option} value={option}>
                    {CONNECTOR_LABELS[option] ?? option}
                  </option>
                ))}
              </select>
              <input
                placeholder={t("connectionName")}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <input
                placeholder="https://… (base URL / clone URL)"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <input
                type="password"
                autoComplete="off"
                placeholder={t("secretValuePlaceholder")}
                value={secretValue}
                onChange={(e) => setSecretValue(e.target.value)}
              />
              <input
                placeholder={`${t("orEnvVar")} — ESTIMO_SECRET_…`}
                value={secretEnv}
                onChange={(e) => setSecretEnv(e.target.value)}
              />
              <input
                placeholder={t("aclKeysPlaceholder")}
                value={aclKeys}
                onChange={(e) => setAclKeys(e.target.value)}
              />
              <input
                style={{
                  gridColumn: "1 / span 2",
                  borderColor: configValid ? undefined : "var(--crit)",
                }}
                placeholder={`config JSON — ${CONFIG_HINTS[kind] ?? "{}"}`}
                value={configText}
                onChange={(e) => setConfigText(e.target.value)}
              />
              <button
                type="button"
                className="btn p"
                style={{ justifyContent: "center" }}
                disabled={busy || !name || !baseUrl || !configValid}
                onClick={() =>
                  run(async () => {
                    await api.createConnection({
                      kind,
                      name,
                      base_url: baseUrl,
                      config: JSON.parse(configText || "{}"),
                      secret_env: secretEnv || null,
                      secret: secretValue || null,
                      acl_keys: aclKeys
                        ? aclKeys
                            .split(",")
                            .map((key) => key.trim())
                            .filter(Boolean)
                        : null,
                    });
                    setName("");
                    setBaseUrl("");
                    setSecretValue("");
                    setSecretEnv("");
                    setAclKeys("");
                    setConfigText("{}");
                    setShowForm(false);
                  })
                }
              >
                {t("save")}
              </button>
            </div>
          </div>
        )}

        {connections.length === 0 ? (
          <div style={{ padding: "26px 18px", color: "var(--mut)", fontSize: 13 }}>
            No connections yet — add the wiki, issue tracker and repositories this deployment
            estimates against.
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))",
              gap: 14,
              padding: "16px 18px",
            }}
          >
            {connections.map((connection) => {
              const run_ = connection.last_run;
              const failed = run_?.status === "failed";
              const running = run_?.status === "running";
              const stats = statsLine(run_?.stats ?? null);
              return (
                <div
                  key={connection.id}
                  className="card"
                  style={{
                    padding: "14px 15px",
                    borderColor: failed ? "var(--crit)" : undefined,
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <span
                      style={{ display: "inline-flex", alignItems: "center", gap: 10, minWidth: 0 }}
                    >
                      <ConnectorMark kind={connection.kind} size={30} />
                      <span style={{ minWidth: 0 }}>
                        <span
                          style={{
                            display: "block",
                            fontFamily: "var(--font-mono)",
                            fontSize: 13,
                            fontWeight: 500,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {connection.name}
                        </span>
                        <span style={{ display: "block", fontSize: 11, color: "var(--mut)" }}>
                          {CONNECTOR_LABELS[connection.kind] ?? connection.kind}
                          {connection.sync_cadence_minutes
                            ? ` · every ${connection.sync_cadence_minutes} ${t("minShort")}`
                            : " · manual sync"}
                        </span>
                      </span>
                    </span>
                    {failed ? (
                      <StatusChip status="crit">{t("errorWord")}</StatusChip>
                    ) : running ? (
                      <StatusChip status="warn">{t("firstSync")}</StatusChip>
                    ) : run_ ? (
                      <StatusChip status="ok">{t("connected")}</StatusChip>
                    ) : (
                      <Chip>{t("neverSynced")}</Chip>
                    )}
                  </div>

                  {failed && run_?.error ? (
                    <div style={{ fontSize: 12, color: "var(--crit)", textWrap: "pretty" }}>
                      {run_.error.slice(0, 180)}
                    </div>
                  ) : running ? (
                    <div
                      style={{
                        height: 6,
                        borderRadius: 3,
                        background: "var(--surf3)",
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          width: "38%",
                          height: "100%",
                          background: "var(--acc)",
                          boxShadow: "0 0 12px var(--acc)",
                          animation: "om-pulse 1.4s ease-in-out infinite",
                        }}
                      />
                    </div>
                  ) : (
                    <div className="mn" style={{ color: "var(--ink2)" }}>
                      {run_ ? (
                        <>
                          {stats || "synced"}
                          <span style={{ color: "var(--mut)" }}>
                            {" "}
                            · {new Date(run_.started_at).toLocaleString(DATE_LOCALE)}
                          </span>
                        </>
                      ) : (
                        t("neverSynced")
                      )}
                    </div>
                  )}

                  {(connection.secret_env && !connection.secret_present) ||
                  (connection.acl_keys ?? []).length > 0 ? (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {connection.secret_env && !connection.secret_present && (
                        <StatusChip status="crit">{t("secretMissing")}</StatusChip>
                      )}
                      {(connection.acl_keys ?? []).slice(0, 3).map((key) => (
                        <Chip key={key}>{key}</Chip>
                      ))}
                    </div>
                  ) : null}

                  <div
                    style={{
                      display: "flex",
                      gap: 6,
                      alignItems: "center",
                      flexWrap: "wrap",
                      borderTop: "1px solid var(--line)",
                      paddingTop: 10,
                    }}
                  >
                    <span style={{ fontSize: 11, color: "var(--mut)" }}>{t("cadenceLabel")}</span>
                    <input
                      style={{ width: 62, padding: "5px 8px" }}
                      placeholder={t("cadenceOff")}
                      value={
                        cadenceEdit[connection.id] ??
                        (connection.sync_cadence_minutes === null
                          ? ""
                          : String(connection.sync_cadence_minutes))
                      }
                      onChange={(event) =>
                        setCadenceEdit({ ...cadenceEdit, [connection.id]: event.target.value })
                      }
                    />
                    <button
                      type="button"
                      className="btn"
                      style={{ padding: "5px 10px" }}
                      disabled={busy}
                      onClick={() => {
                        const raw = (cadenceEdit[connection.id] ?? "").trim();
                        const minutes = raw === "" ? null : Number(raw);
                        if (minutes !== null && !Number.isFinite(minutes)) return;
                        run(() => api.setCadence(connection.id, minutes));
                      }}
                    >
                      {t("save")}
                    </button>
                    <span style={{ flex: 1 }} />
                    <button
                      type="button"
                      className="btn glow"
                      style={{ padding: "5px 10px" }}
                      disabled={busy || running}
                      onClick={() => run(() => api.triggerSync(connection.id))}
                    >
                      {t("syncNow")}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      style={{ padding: "5px 10px" }}
                      aria-label="delete connection"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            t("confirmDeleteConnection").replace("{name}", connection.name),
                          )
                        ) {
                          run(() => api.deleteConnection(connection.id));
                        }
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  {(connection.kind === "confluence" || connection.kind === "jira") && (
                    <div
                      style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}
                    >
                      <input
                        style={{ width: 150, padding: "5px 8px" }}
                        placeholder={t("pinPlaceholder")}
                        value={pinRef[connection.id] ?? ""}
                        onChange={(event) =>
                          setPinRef({ ...pinRef, [connection.id]: event.target.value })
                        }
                      />
                      <button
                        type="button"
                        className="btn"
                        style={{ padding: "5px 10px" }}
                        disabled={busy || !(pinRef[connection.id] ?? "").trim()}
                        onClick={() =>
                          run(async () => {
                            const pin = await api.createPin(
                              connection.id,
                              (pinRef[connection.id] ?? "").trim(),
                            );
                            setPinNote({
                              ...pinNote,
                              [connection.id]: pin.last_error
                                ? `${pin.ref}: ${pin.last_error}`
                                : `${pin.ref} ✓`,
                            });
                            setPinRef({ ...pinRef, [connection.id]: "" });
                          })
                        }
                      >
                        {t("pinNow")}
                      </button>
                      {pinNote[connection.id] && (
                        <span className="mn" style={{ fontSize: 11, color: "var(--ink2)" }}>
                          {pinNote[connection.id]}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ---- Model gateway — the stage → profile table (ADR-0001 UI contract). ---- */}
      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title={t("gatewaySection")}
          subtitle="One OpenAI-compatible endpoint; stages route to named model profiles."
          right={
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {gatewayResult &&
                (gatewayResult.ok ? (
                  <StatusChip status="ok">
                    {gatewayResult.model} · {gatewayResult.latency_ms} ms · {t("gatewayOk")}
                  </StatusChip>
                ) : (
                  <StatusChip status="crit">
                    {gatewayResult.reason === "not-configured"
                      ? t("gatewayUnset")
                      : (gatewayResult.error ?? "error").slice(0, 90)}
                  </StatusChip>
                ))}
              <button type="button" className="btn" disabled={checking} onClick={checkGateway}>
                {checking ? t("testing") : t("testGateway")}
              </button>
            </div>
          }
        />
        <div style={{ padding: "14px 18px" }}>
          {system ? (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                {system.gateway.source === "panel" ? (
                  <StatusChip status="ok">{t("sourcePanel")}</StatusChip>
                ) : system.gateway.source === "unset" ? (
                  <StatusChip status="warn">{t("gatewayUnset")}</StatusChip>
                ) : (
                  <Chip>{t("sourceEnv")}</Chip>
                )}
                {/* "API key missing" is a PROBLEM only when a gateway exists without
                    one. On a fresh deployment it is just the second half of "nothing
                    is configured yet", and two red chips for one fact read as two
                    faults. */}
                {system.gateway.api_key_present ? (
                  <StatusChip status="ok">{t("keyConfigured")}</StatusChip>
                ) : (
                  system.gateway.configured && (
                    <StatusChip status="crit">{t("keyMissing")}</StatusChip>
                  )
                )}
                {!system.gateway.secrets_encrypted && (
                  <StatusChip status="warn">{t("unencryptedWarn")}</StatusChip>
                )}
                {!system.gateway.stored_key_readable && (
                  <StatusChip status="crit">{t("keyUnreadable")}</StatusChip>
                )}
                {gwSaved && <StatusChip status="ok">{t("savedOk")}</StatusChip>}
              </div>
              {!system.gateway.configured && (
                <div
                  style={{
                    marginTop: 10,
                    fontSize: 12.5,
                    color: "var(--ink2)",
                    textWrap: "pretty",
                  }}
                >
                  {t("gatewayUnsetHint")}
                </div>
              )}

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "150px 1fr",
                  rowGap: 9,
                  columnGap: 14,
                  alignItems: "center",
                  marginTop: 12,
                }}
              >
                <Lbl>{t("baseUrlLabel")}</Lbl>
                <input
                  style={{ minWidth: 320 }}
                  value={gwBaseUrl}
                  onChange={(e) => setGwBaseUrl(e.target.value)}
                />
                <Lbl>{t("apiKeyLabel")}</Lbl>
                <input
                  type="password"
                  autoComplete="off"
                  style={{ minWidth: 320 }}
                  placeholder={
                    system.gateway.api_key_present
                      ? t("apiKeySavedPlaceholder")
                      : t("apiKeyUnsetPlaceholder")
                  }
                  value={gwApiKey}
                  onChange={(e) => setGwApiKey(e.target.value)}
                />
                <Lbl>
                  {t("timeoutShort")} · {t("retriesShort")}
                </Lbl>
                <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    style={{ width: 76 }}
                    value={gwTimeout}
                    onChange={(e) => setGwTimeout(e.target.value)}
                  />
                  <span className="muted">s ·</span>
                  <input
                    style={{ width: 76 }}
                    value={gwConnectTimeout}
                    onChange={(e) => setGwConnectTimeout(e.target.value)}
                  />
                  <span className="muted">s connect ·</span>
                  <input
                    style={{ width: 56 }}
                    value={gwRetries}
                    onChange={(e) => setGwRetries(e.target.value)}
                  />
                  <span className="muted">retry</span>
                </span>
              </div>

              <table className="dt" style={{ marginTop: 12 }}>
                <thead>
                  <tr>
                    <th>{t("stageHeader")}</th>
                    <th>{t("profileHeader")}</th>
                    <th style={{ width: 40 }} />
                  </tr>
                </thead>
                <tbody>
                  {gwProfiles.map((row, index) => (
                    <tr key={index}>
                      <td>
                        <input
                          value={row.stage}
                          onChange={(e) =>
                            setGwProfiles(
                              gwProfiles.map((r, i) =>
                                i === index ? { ...r, stage: e.target.value } : r,
                              ),
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          value={row.profile}
                          onChange={(e) =>
                            setGwProfiles(
                              gwProfiles.map((r, i) =>
                                i === index ? { ...r, profile: e.target.value } : r,
                              ),
                            )
                          }
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn"
                          aria-label="remove profile"
                          onClick={() =>
                            setGwProfiles(gwProfiles.filter((_, i) => i !== index))
                          }
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {/* Same rule: with no gateway, "every model call will fail" describes a
                  breakage that has not happened — nothing is calling anything. It is a
                  real warning only once an endpoint exists with no routing. */}
              {gwProfiles.length === 0 && (
                <div style={{ marginTop: 10 }}>
                  {system.gateway.configured ? (
                    <StatusChip status="crit">{t("noProfiles")}</StatusChip>
                  ) : (
                    <Lbl>{t("noProfilesYet")}</Lbl>
                  )}
                </div>
              )}

              <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setGwProfiles([...gwProfiles, { stage: "", profile: "" }])}
                >
                  {t("addProfile")}
                </button>
                <div style={{ flex: 1 }} />
                {/* Two different acts wearing one label. With an environment
                    gateway underneath, dropping the override REVERTS to it. Without
                    one — the default now that the gateway is panel-managed — the
                    same click leaves the deployment with no gateway at all, so it
                    says that instead and asks first. */}
                {system.gateway.source === "panel" && (
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    onClick={() => {
                      if (
                        !system.gateway.env_present &&
                        !window.confirm(t("clearGatewayConfirm"))
                      ) {
                        return;
                      }
                      void saveGateway(true);
                    }}
                  >
                    {system.gateway.env_present ? t("revertEnv") : t("clearGateway")}
                  </button>
                )}
                <button
                  type="button"
                  className="btn p"
                  disabled={busy || !gwBaseUrl.trim()}
                  onClick={() => saveGateway(false)}
                >
                  {t("saveGateway")}
                </button>
              </div>

              <div style={{ marginTop: 10, textWrap: "pretty" }}>
                <Lbl>{t("gatewayHint")}</Lbl>
              </div>
            </>
          ) : (
            <div style={{ color: "var(--mut)", fontSize: 13 }}>—</div>
          )}
        </div>
      </div>

      {/* ---- System strip: reported, never edited (env-only config). ---- */}
      {system && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
            padding: "10px 14px",
            border: "1px solid var(--line)",
            borderRadius: "var(--r2)",
            background: "oklch(0.18 0.014 295)",
          }}
        >
          <Lbl>System</Lbl>
          {system.auth.mode === "oidc" ? (
            <StatusChip status="ok">{t("authModeOidc")}</StatusChip>
          ) : (
            <StatusChip status="warn">{t("authModeOpen")}</StatusChip>
          )}
          {system.auth.mode === "oidc" && <Mn>{system.auth.issuer}</Mn>}
          <Mn>v{system.version}</Mn>
          <Mn>
            {system.database.role}@{system.database.host}/{system.database.name}
          </Mn>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: "var(--mut)" }}>{t("envOnlyHint")}</span>
        </div>
      )}
    </section>
  );
}
