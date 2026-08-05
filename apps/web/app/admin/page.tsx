"use client";

/** 10 · Admin — "Boring but transparent: sync status, error queues, roles."
 *
 * Connection tiles carry the design's canonical error shape: what failed, the code,
 * and the exact remedial path. Credentials entered here are sealed before storage
 * (ADR-0008 — encrypted when ESTIMO_SECRET_KEY is set) and never serialized back;
 * the env-var-name lane remains available. The Model gateway card EDITS runtime
 * config: what it saves overrides the environment immediately. */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type ConnectionEntry,
  type GatewayCheckResult,
  type SystemInfo,
} from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, StatusChip } from "@/components/ui";
import { IconAdmin } from "@/components/icons";

const KINDS = ["confluence", "bitbucket", "github", "gitlab", "git", "jira"];

const ROLE_ROWS: {
  role: "roleAnalyst" | "roleReviewer" | "roleSigning" | "roleAdmin";
  sign: "maySignNothing" | "maySignLines" | "maySignFull";
}[] = [
  { role: "roleAnalyst", sign: "maySignNothing" },
  { role: "roleReviewer", sign: "maySignNothing" },
  { role: "roleSigning", sign: "maySignLines" },
  { role: "roleAdmin", sign: "maySignFull" },
];

export default function AdminPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [connections, setConnections] = useState<ConnectionEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [gatewayResult, setGatewayResult] = useState<GatewayCheckResult | null>(
    null,
  );
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
  const [gwProfiles, setGwProfiles] = useState<
    { stage: string; profile: string }[]
  >([]);
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
          info.gateway.timeout_seconds === null
            ? ""
            : String(info.gateway.timeout_seconds),
        );
        setGwConnectTimeout(
          info.gateway.connect_timeout_seconds === null
            ? ""
            : String(info.gateway.connect_timeout_seconds),
        );
        setGwRetries(
          info.gateway.max_retries === null
            ? ""
            : String(info.gateway.max_retries),
        );
        setGwProfiles(
          Object.entries(info.gateway.profiles).map(([stage, profile]) => ({
            stage,
            profile,
          })),
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
    setLocale(detectLocale());
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
    if (!Number.isFinite(value))
      throw new Error(`${label}: not a number — "${raw}"`);
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
          (row, index) =>
            filled.findIndex((other) => other.stage === row.stage) !== index,
        );
        if (duplicate) throw new Error(`duplicate stage: "${duplicate.stage}"`);

        const timeout = numeric(gwTimeout, t(locale, "timeoutShort"));
        const connectTimeout = numeric(
          gwConnectTimeout,
          t(locale, "timeoutShort"),
        );
        const retries = numeric(gwRetries, t(locale, "retriesShort"));

        await api.putGateway({
          // Only send the URL when the operator actually changed it: the value in
          // the field came from /v1/system with userinfo STRIPPED, so echoing it
          // back would persist a redacted (broken) URL over a working one.
          ...(gwBaseUrl.trim() !== (system?.gateway.base_url ?? "")
            ? { base_url: gwBaseUrl.trim() }
            : {}),
          ...(gwApiKey ? { api_key: gwApiKey } : {}),
          profiles: Object.fromEntries(
            filled.map((row) => [row.stage, row.profile]),
          ),
          ...(timeout !== null ? { timeout_seconds: timeout } : {}),
          ...(connectTimeout !== null
            ? { connect_timeout_seconds: connectTimeout }
            : {}),
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
    <section className="scr">
      <div className="page-h">
        <IconAdmin size={18} />
        <h2>{t(locale, "admin")}</h2>
        <span className="sub">{t(locale, "adminSubtitle")}</span>
      </div>

      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title={t(locale, "connections")}
          right={
            <button
              type="button"
              className="btn"
              onClick={() => setShowForm(!showForm)}
            >
              {t(locale, "addConnection")}
            </button>
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

        {showForm && (
          <div
            style={{
              padding: "14px 18px",
              borderBottom: "1px solid var(--line)",
              background: "var(--surf2)",
            }}
          >
            <div
              style={{
                fontSize: 12.5,
                color: "var(--ink2)",
                marginBottom: 10,
                textWrap: "pretty",
              }}
            >
              {t(locale, "secretEnvHint")}
            </div>
            <div
              style={{
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                alignItems: "center",
              }}
            >
              <select
                aria-label="kind"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                {KINDS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <input
                placeholder={t(locale, "connectionName")}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <input
                style={{ minWidth: 280 }}
                placeholder="https://… (base URL / clone URL)"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <input
                type="password"
                autoComplete="off"
                style={{ minWidth: 230 }}
                placeholder={t(locale, "secretValuePlaceholder")}
                value={secretValue}
                onChange={(e) => setSecretValue(e.target.value)}
              />
              <input
                placeholder={`${t(locale, "orEnvVar")} — ESTIMO_SECRET_…`}
                value={secretEnv}
                onChange={(e) => setSecretEnv(e.target.value)}
              />
              <input
                placeholder={t(locale, "aclKeysPlaceholder")}
                value={aclKeys}
                onChange={(e) => setAclKeys(e.target.value)}
              />
              <input
                style={{
                  minWidth: 220,
                  borderColor: configValid ? undefined : "var(--crit)",
                }}
                placeholder='config JSON — {"space_keys": ["AUR"]}'
                value={configText}
                onChange={(e) => setConfigText(e.target.value)}
              />
              <button
                type="button"
                className="btn p"
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
                {t(locale, "save")}
              </button>
            </div>
          </div>
        )}

        {connections.length === 0 ? (
          <div
            style={{ padding: "26px 18px", color: "var(--mut)", fontSize: 13 }}
          >
            —
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 14,
              padding: "16px 18px",
            }}
          >
            {connections.map((connection) => {
              const run_ = connection.last_run;
              const failed = run_?.status === "failed";
              const running = run_?.status === "running";
              return (
                <div
                  key={connection.id}
                  className="card"
                  style={{
                    padding: "13px 15px",
                    borderColor: failed ? "var(--crit)" : undefined,
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
                    <span style={{ fontSize: 14, fontWeight: 500 }}>
                      {connection.name}
                    </span>
                    {failed ? (
                      <StatusChip status="crit">
                        {t(locale, "errorWord")}
                      </StatusChip>
                    ) : running ? (
                      <StatusChip status="warn">
                        {t(locale, "firstSync")}
                      </StatusChip>
                    ) : run_ ? (
                      <StatusChip status="ok">
                        {t(locale, "connected")}
                      </StatusChip>
                    ) : (
                      <Chip>{t(locale, "neverSynced")}</Chip>
                    )}
                  </div>

                  <div
                    style={{
                      display: "flex",
                      gap: 6,
                      marginTop: 8,
                      flexWrap: "wrap",
                    }}
                  >
                    <Chip>{connection.kind}</Chip>
                    {connection.secret_env && !connection.secret_present && (
                      <StatusChip status="crit">
                        {t(locale, "secretMissing")}
                      </StatusChip>
                    )}
                    {(connection.acl_keys ?? []).slice(0, 2).map((key) => (
                      <Chip key={key}>{key}</Chip>
                    ))}
                  </div>

                  {failed && run_?.error ? (
                    <div
                      style={{
                        fontSize: 12.5,
                        color: "var(--ink2)",
                        marginTop: 9,
                        textWrap: "pretty",
                      }}
                    >
                      {run_.error.slice(0, 180)}
                    </div>
                  ) : running ? (
                    <>
                      <div
                        style={{
                          height: 6,
                          borderRadius: 3,
                          background: "var(--surf3)",
                          marginTop: 11,
                          overflow: "hidden",
                        }}
                      >
                        <div
                          style={{
                            width: "38%",
                            height: "100%",
                            background: "var(--acc)",
                          }}
                        />
                      </div>
                      <div
                        style={{
                          fontSize: 12,
                          color: "var(--ink2)",
                          marginTop: 8,
                        }}
                      >
                        {t(locale, "firstSyncHint")}
                      </div>
                    </>
                  ) : (
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--ink2)",
                        marginTop: 9,
                      }}
                    >
                      {run_
                        ? `${t(locale, "lastSyncAgo")} ${new Date(run_.started_at).toLocaleString(locale)}${
                            run_.stats
                              ? ` · ${JSON.stringify(run_.stats).slice(1, 60)}`
                              : ""
                          }`
                        : t(locale, "neverSynced")}
                    </div>
                  )}

                  <div
                    style={{
                      display: "flex",
                      gap: 6,
                      marginTop: 11,
                      alignItems: "center",
                      flexWrap: "wrap",
                    }}
                  >
                    <span style={{ fontSize: 11.5, color: "var(--mut)" }}>
                      {t(locale, "cadenceLabel")}
                    </span>
                    <input
                      style={{ width: 64 }}
                      placeholder={t(locale, "cadenceOff")}
                      value={
                        cadenceEdit[connection.id] ??
                        (connection.sync_cadence_minutes === null
                          ? ""
                          : String(connection.sync_cadence_minutes))
                      }
                      onChange={(event) =>
                        setCadenceEdit({
                          ...cadenceEdit,
                          [connection.id]: event.target.value,
                        })
                      }
                    />
                    <button
                      type="button"
                      className="btn"
                      disabled={busy}
                      onClick={() => {
                        const raw = (cadenceEdit[connection.id] ?? "").trim();
                        const minutes = raw === "" ? null : Number(raw);
                        if (minutes !== null && !Number.isFinite(minutes)) return;
                        run(() => api.setCadence(connection.id, minutes));
                      }}
                    >
                      {t(locale, "save")}
                    </button>
                  </div>
                  {(connection.kind === "confluence" ||
                    connection.kind === "jira") && (
                    <div
                      style={{
                        display: "flex",
                        gap: 6,
                        marginTop: 8,
                        alignItems: "center",
                        flexWrap: "wrap",
                      }}
                    >
                      <input
                        style={{ width: 150 }}
                        placeholder={t(locale, "pinPlaceholder")}
                        value={pinRef[connection.id] ?? ""}
                        onChange={(event) =>
                          setPinRef({
                            ...pinRef,
                            [connection.id]: event.target.value,
                          })
                        }
                      />
                      <button
                        type="button"
                        className="btn"
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
                        {t(locale, "pinNow")}
                      </button>
                      {pinNote[connection.id] && (
                        <span
                          style={{ fontSize: 11.5, color: "var(--ink2)" }}
                          className="mn"
                        >
                          {pinNote[connection.id]}
                        </span>
                      )}
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8, marginTop: 11 }}>
                    <button
                      type="button"
                      className="btn"
                      disabled={busy || running}
                      onClick={() => run(() => api.triggerSync(connection.id))}
                    >
                      {t(locale, "syncNow")}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            t(locale, "confirmDeleteConnection").replace(
                              "{name}",
                              connection.name,
                            ),
                          )
                        ) {
                          run(() => api.deleteConnection(connection.id));
                        }
                      }}
                    >
                      ✕
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Model gateway — the design's stage → profile table (ADR-0001 UI contract). */}
      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title={t(locale, "gatewaySection")}
          right={
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {gatewayResult &&
                (gatewayResult.ok ? (
                  <StatusChip status="ok">
                    {gatewayResult.model} · {gatewayResult.latency_ms} ms ·{" "}
                    {t(locale, "gatewayOk")}
                  </StatusChip>
                ) : (
                  <StatusChip status="crit">
                    {gatewayResult.reason === "not-configured"
                      ? t(locale, "gatewayUnset")
                      : (gatewayResult.error ?? "error").slice(0, 90)}
                  </StatusChip>
                ))}
              <button
                type="button"
                className="btn"
                disabled={checking}
                onClick={checkGateway}
              >
                {checking ? t(locale, "testing") : t(locale, "testGateway")}
              </button>
            </div>
          }
        />
        <div style={{ padding: "14px 18px" }}>
          {system ? (
            <>
              <div
                style={{
                  display: "flex",
                  gap: 8,
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                {system.gateway.source === "panel" ? (
                  <StatusChip status="ok">
                    {t(locale, "sourcePanel")}
                  </StatusChip>
                ) : system.gateway.source === "unset" ? (
                  <StatusChip status="warn">
                    {t(locale, "gatewayUnset")}
                  </StatusChip>
                ) : (
                  <Chip>{t(locale, "sourceEnv")}</Chip>
                )}
                {/* "API key missing" is a PROBLEM only when a gateway exists without
                    one. On a fresh deployment it is just the second half of "nothing
                    is configured yet", and two red chips for one fact read as two
                    faults. */}
                {system.gateway.api_key_present ? (
                  <StatusChip status="ok">
                    {t(locale, "keyConfigured")}
                  </StatusChip>
                ) : (
                  system.gateway.configured && (
                    <StatusChip status="crit">
                      {t(locale, "keyMissing")}
                    </StatusChip>
                  )
                )}
                {!system.gateway.secrets_encrypted && (
                  <StatusChip status="warn">
                    {t(locale, "unencryptedWarn")}
                  </StatusChip>
                )}
                {!system.gateway.stored_key_readable && (
                  <StatusChip status="crit">
                    {t(locale, "keyUnreadable")}
                  </StatusChip>
                )}
                {gwSaved && (
                  <StatusChip status="ok">{t(locale, "savedOk")}</StatusChip>
                )}
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
                  {t(locale, "gatewayUnsetHint")}
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
                <Lbl>{t(locale, "baseUrlLabel")}</Lbl>
                <input
                  style={{ fontFamily: "var(--font-mono)", minWidth: 320 }}
                  value={gwBaseUrl}
                  onChange={(e) => setGwBaseUrl(e.target.value)}
                />
                <Lbl>{t(locale, "apiKeyLabel")}</Lbl>
                <input
                  type="password"
                  autoComplete="off"
                  style={{ minWidth: 320 }}
                  placeholder={
                    system.gateway.api_key_present
                      ? t(locale, "apiKeySavedPlaceholder")
                      : t(locale, "apiKeyUnsetPlaceholder")
                  }
                  value={gwApiKey}
                  onChange={(e) => setGwApiKey(e.target.value)}
                />
                <Lbl>
                  {t(locale, "timeoutShort")} · {t(locale, "retriesShort")}
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
                    <th>{t(locale, "stageHeader")}</th>
                    <th>{t(locale, "profileHeader")}</th>
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
                                i === index
                                  ? { ...r, stage: e.target.value }
                                  : r,
                              ),
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          style={{ fontFamily: "var(--font-mono)" }}
                          value={row.profile}
                          onChange={(e) =>
                            setGwProfiles(
                              gwProfiles.map((r, i) =>
                                i === index
                                  ? { ...r, profile: e.target.value }
                                  : r,
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
                            setGwProfiles(
                              gwProfiles.filter((_, i) => i !== index),
                            )
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
                    <StatusChip status="crit">
                      {t(locale, "noProfiles")}
                    </StatusChip>
                  ) : (
                    <Lbl>{t(locale, "noProfilesYet")}</Lbl>
                  )}
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  gap: 8,
                  marginTop: 12,
                  alignItems: "center",
                }}
              >
                <button
                  type="button"
                  className="btn"
                  onClick={() =>
                    setGwProfiles([...gwProfiles, { stage: "", profile: "" }])
                  }
                >
                  {t(locale, "addProfile")}
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
                        !window.confirm(t(locale, "clearGatewayConfirm"))
                      ) {
                        return;
                      }
                      void saveGateway(true);
                    }}
                  >
                    {system.gateway.env_present
                      ? t(locale, "revertEnv")
                      : t(locale, "clearGateway")}
                  </button>
                )}
                <button
                  type="button"
                  className="btn p"
                  disabled={busy || !gwBaseUrl.trim()}
                  onClick={() => saveGateway(false)}
                >
                  {t(locale, "saveGateway")}
                </button>
              </div>

              <div style={{ marginTop: 10, textWrap: "pretty" }}>
                <Lbl>{t(locale, "gatewayHint")}</Lbl>
              </div>
            </>
          ) : (
            <div style={{ color: "var(--mut)", fontSize: 13 }}>—</div>
          )}
        </div>
      </div>

      {/* Runtime & authentication — reported, never edited (env-only config). */}
      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader title={t(locale, "runtimeSection")} />
        <div style={{ padding: "14px 18px" }}>
          {system ? (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "170px 1fr",
                  rowGap: 9,
                  columnGap: 14,
                  alignItems: "baseline",
                  fontSize: 13,
                }}
              >
                <Lbl>{t(locale, "authModeLabel")}</Lbl>
                <span
                  style={{
                    display: "flex",
                    gap: 8,
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  {system.auth.mode === "oidc" ? (
                    <>
                      <StatusChip status="ok">
                        {t(locale, "authModeOidc")}
                      </StatusChip>
                      <Mn>{system.auth.issuer}</Mn>
                      {system.auth.audience && (
                        <Chip>aud {system.auth.audience}</Chip>
                      )}
                      <Chip>roles ← {system.auth.role_claim}</Chip>
                      <Chip>tenant ← {system.auth.tenant_claim}</Chip>
                      {system.auth.acl_claim ? (
                        <Chip>acl ← {system.auth.acl_claim}</Chip>
                      ) : (
                        <StatusChip status="warn">
                          {t(locale, "aclClaimUnset")}
                        </StatusChip>
                      )}
                    </>
                  ) : (
                    <StatusChip status="warn">
                      {t(locale, "authModeOpen")}
                    </StatusChip>
                  )}
                </span>
                <Lbl>{t(locale, "apiVersionLabel")}</Lbl>
                <Mn>{system.version}</Mn>
                <Lbl>{t(locale, "databaseLabel")}</Lbl>
                <Mn>
                  {system.database.role}@{system.database.host}/
                  {system.database.name}
                </Mn>
                <Lbl>{t(locale, "corsLabel")}</Lbl>
                <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {system.cors_origins.map((origin) => (
                    <Chip key={origin}>{origin}</Chip>
                  ))}
                </span>
              </div>
              <div style={{ marginTop: 12, textWrap: "pretty" }}>
                <Lbl>{t(locale, "envOnlyHint")}</Lbl>
              </div>
            </>
          ) : (
            <div style={{ color: "var(--mut)", fontSize: 13 }}>—</div>
          )}
        </div>
      </div>

      {/* Roles */}
      <div className="card" style={{ overflow: "hidden" }}>
        <BandHeader title={t(locale, "rolesSection")} />
        <div style={{ padding: "14px 18px" }}>
          <table className="dt">
            <thead>
              <tr>
                <th>{t(locale, "rolesSection")}</th>
                <th style={{ width: 180 }}>{t(locale, "maySign")}</th>
              </tr>
            </thead>
            <tbody>
              {ROLE_ROWS.map((row) => (
                <tr key={row.role}>
                  <td style={{ color: "var(--ink2)" }}>
                    {t(locale, row.role)}
                  </td>
                  <td>
                    {row.sign === "maySignNothing" ? (
                      <Mn style={{ color: "var(--mut)" }}>—</Mn>
                    ) : (
                      t(locale, row.sign)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 10 }}>
            <Lbl>{t(locale, "rolesFootnote")}</Lbl>
          </div>
        </div>
      </div>
    </section>
  );
}
