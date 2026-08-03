"use client";

/** 10 · Admin — "Boring but transparent: sync status, error queues, roles."
 *
 * Connection tiles carry the design's canonical error shape: what failed, the code,
 * and the exact remedial path. Credentials never pass through this UI — a connection
 * stores only the NAME of an env var on the API container. */

import { useCallback, useEffect, useState } from "react";
import { api, type ConnectionEntry, type GatewayCheckResult, type SystemInfo } from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";
import { BandHeader, Chip, Lbl, Mn, StatusChip } from "@/components/ui";
import { IconAdmin } from "@/components/icons";

const KINDS = ["confluence", "bitbucket", "github", "gitlab", "git", "jira"];

const ROLE_ROWS: { role: "roleAnalyst" | "roleReviewer" | "roleSigning" | "roleAdmin"; sign: "maySignNothing" | "maySignLines" | "maySignFull" }[] =
  [
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
  const [gatewayResult, setGatewayResult] = useState<GatewayCheckResult | null>(null);
  const [checking, setChecking] = useState(false);

  const [kind, setKind] = useState("bitbucket");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [configText, setConfigText] = useState("{}");
  const [secretEnv, setSecretEnv] = useState("");
  const [aclKeys, setAclKeys] = useState("");

  const refresh = useCallback(() => {
    api.listConnections().then(setConnections).catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    setLocale(detectLocale());
    refresh();
    api.systemInfo().then(setSystem).catch((err) => setError(String(err)));
  }, [refresh]);

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
            <button type="button" className="btn" onClick={() => setShowForm(!showForm)}>
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
            <div style={{ fontSize: 12.5, color: "var(--ink2)", marginBottom: 10, textWrap: "pretty" }}>
              {t(locale, "secretEnvHint")}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <select aria-label="kind" value={kind} onChange={(e) => setKind(e.target.value)}>
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
                placeholder="ESTIMO_SECRET_… (env var)"
                value={secretEnv}
                onChange={(e) => setSecretEnv(e.target.value)}
              />
              <input
                placeholder={t(locale, "aclKeysPlaceholder")}
                value={aclKeys}
                onChange={(e) => setAclKeys(e.target.value)}
              />
              <input
                style={{ minWidth: 220, borderColor: configValid ? undefined : "var(--crit)" }}
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
                      acl_keys: aclKeys
                        ? aclKeys.split(",").map((key) => key.trim()).filter(Boolean)
                        : null,
                    });
                    setName("");
                    setBaseUrl("");
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
          <div style={{ padding: "26px 18px", color: "var(--mut)", fontSize: 13 }}>—</div>
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
                    <span style={{ fontSize: 14, fontWeight: 500 }}>{connection.name}</span>
                    {failed ? (
                      <StatusChip status="crit">{t(locale, "errorWord")}</StatusChip>
                    ) : running ? (
                      <StatusChip status="warn">{t(locale, "firstSync")}</StatusChip>
                    ) : run_ ? (
                      <StatusChip status="ok">{t(locale, "connected")}</StatusChip>
                    ) : (
                      <Chip>{t(locale, "neverSynced")}</Chip>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                    <Chip>{connection.kind}</Chip>
                    {connection.secret_env && !connection.secret_present && (
                      <StatusChip status="crit">{t(locale, "secretMissing")}</StatusChip>
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
                        <div style={{ width: "38%", height: "100%", background: "var(--acc)" }} />
                      </div>
                      <div style={{ fontSize: 12, color: "var(--ink2)", marginTop: 8 }}>
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
                            run_.stats ? ` · ${JSON.stringify(run_.stats).slice(1, 60)}` : ""
                          }`
                        : t(locale, "neverSynced")}
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
                            t(locale, "confirmDeleteConnection").replace("{name}", connection.name),
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
                    {(gatewayResult.error ?? "error").slice(0, 90)}
                  </StatusChip>
                ))}
              <button type="button" className="btn" disabled={checking} onClick={checkGateway}>
                {checking ? t(locale, "testing") : t(locale, "testGateway")}
              </button>
            </div>
          }
        />
        <div style={{ padding: "14px 18px" }}>
          {system ? (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <Mn>{system.gateway.base_url}</Mn>
                {system.gateway.api_key_present ? (
                  <StatusChip status="ok">{t(locale, "keyConfigured")}</StatusChip>
                ) : (
                  <StatusChip status="crit">{t(locale, "keyMissing")}</StatusChip>
                )}
                <Chip>
                  {t(locale, "timeoutShort")} {system.gateway.timeout_seconds}s
                </Chip>
                <Chip>
                  {t(locale, "retriesShort")} {system.gateway.max_retries}
                </Chip>
              </div>
              {Object.keys(system.gateway.profiles).length === 0 ? (
                <div style={{ marginTop: 12 }}>
                  <StatusChip status="crit">{t(locale, "noProfiles")}</StatusChip>
                </div>
              ) : (
                <table className="dt" style={{ marginTop: 12 }}>
                  <thead>
                    <tr>
                      <th>{t(locale, "stageHeader")}</th>
                      <th>{t(locale, "profileHeader")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(system.gateway.profiles).map(([stage, profile]) => (
                      <tr key={stage}>
                        <td style={{ color: "var(--ink2)" }}>{stage}</td>
                        <td>
                          <Mn>{profile}</Mn>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
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
                <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  {system.auth.mode === "oidc" ? (
                    <>
                      <StatusChip status="ok">{t(locale, "authModeOidc")}</StatusChip>
                      <Mn>{system.auth.issuer}</Mn>
                      {system.auth.audience && <Chip>aud {system.auth.audience}</Chip>}
                      <Chip>roles ← {system.auth.role_claim}</Chip>
                      <Chip>tenant ← {system.auth.tenant_claim}</Chip>
                      {system.auth.acl_claim ? (
                        <Chip>acl ← {system.auth.acl_claim}</Chip>
                      ) : (
                        <StatusChip status="warn">{t(locale, "aclClaimUnset")}</StatusChip>
                      )}
                    </>
                  ) : (
                    <StatusChip status="warn">{t(locale, "authModeOpen")}</StatusChip>
                  )}
                </span>
                <Lbl>{t(locale, "apiVersionLabel")}</Lbl>
                <Mn>{system.version}</Mn>
                <Lbl>{t(locale, "databaseLabel")}</Lbl>
                <Mn>
                  {system.database.role}@{system.database.host}/{system.database.name}
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
                  <td style={{ color: "var(--ink2)" }}>{t(locale, row.role)}</td>
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
