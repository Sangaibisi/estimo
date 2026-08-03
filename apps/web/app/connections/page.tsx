"use client";

/** Admin → Connections (S9): live sources + canonical-pages curation.
 * Secrets never pass through this UI — connections reference the NAME of an env
 * var set on the API container. */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type CanonicalEntry, type ConnectionEntry } from "@/lib/api";
import { detectLocale, t, type Locale } from "@/lib/i18n";

const KINDS = ["confluence", "bitbucket", "github", "gitlab", "git", "jira"];

export default function ConnectionsPage() {
  const [locale, setLocale] = useState<Locale>("en");
  const [connections, setConnections] = useState<ConnectionEntry[]>([]);
  const [canonical, setCanonical] = useState<CanonicalEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [kind, setKind] = useState("bitbucket");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [configText, setConfigText] = useState("{}");
  const [secretEnv, setSecretEnv] = useState("");
  const [aclKeys, setAclKeys] = useState("");
  const [topic, setTopic] = useState("");
  const [approver, setApprover] = useState("");

  const refresh = useCallback(() => {
    api.listConnections().then(setConnections).catch((err) => setError(String(err)));
    api.listCanonical().then(setCanonical).catch((err) => setError(String(err)));
  }, []);
  useEffect(() => {
    setLocale(detectLocale());
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

  let configValid = true;
  try {
    JSON.parse(configText || "{}");
  } catch {
    configValid = false;
  }

  return (
    <main>
      <p>
        <Link href="/">← {t(locale, "estimates")}</Link>
      </p>
      <h1>{t(locale, "connectionsTitle")}</h1>
      {error && (
        <p style={{ color: "var(--crit)" }} role="alert">
          {error}
        </p>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>{t(locale, "newConnection")}</h3>
        <p className="muted" style={{ fontSize: 12 }}>
          {t(locale, "secretEnvHint")}
        </p>
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
            style={{ minWidth: 240, borderColor: configValid ? undefined : "var(--crit)" }}
            placeholder='config JSON — {"space_keys": ["AUR"]}'
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
          />
          <button
            className="primary"
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
              })
            }
          >
            {t(locale, "save")}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        {connections.length === 0 ? (
          <p className="muted">—</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t(locale, "connectionName")}</th>
                <th>kind</th>
                <th>{t(locale, "lastSync")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {connections.map((connection) => (
                <tr key={connection.id}>
                  <td>
                    {connection.name}
                    {connection.secret_env && !connection.secret_present && (
                      <span className="chip" style={{ color: "var(--crit)", marginLeft: 6 }}>
                        {t(locale, "secretMissing")}
                      </span>
                    )}
                  </td>
                  <td>
                    <span className="chip">{connection.kind}</span>
                  </td>
                  <td>
                    {connection.last_run ? (
                      <>
                        <span
                          className="chip"
                          style={{
                            color:
                              connection.last_run.status === "succeeded"
                                ? "var(--ok)"
                                : connection.last_run.status === "failed"
                                  ? "var(--crit)"
                                  : "var(--mut)",
                          }}
                        >
                          {connection.last_run.status}
                        </span>{" "}
                        <span className="muted" style={{ fontSize: 12 }}>
                          {new Date(connection.last_run.started_at).toLocaleString(locale)}
                        </span>
                        {connection.last_run.error && (
                          <div className="muted" style={{ fontSize: 12, color: "var(--crit)" }}>
                            {connection.last_run.error.slice(0, 160)}
                          </div>
                        )}
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button disabled={busy} onClick={() => run(() => api.triggerSync(connection.id))}>
                      {t(locale, "syncNow")}
                    </button>{" "}
                    <button
                      disabled={busy}
                      onClick={() => run(() => api.deleteConnection(connection.id))}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>{t(locale, "canonicalTitle")}</h2>
      <p className="muted" style={{ fontSize: 12 }}>
        {t(locale, "canonicalHint")}
      </p>
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input
            style={{ minWidth: 260 }}
            placeholder={t(locale, "canonicalTopic")}
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <button
            disabled={busy || !topic.trim()}
            onClick={() =>
              run(async () => {
                await api.createCanonical(topic.trim());
                setTopic("");
              })
            }
          >
            {t(locale, "generateCandidate")}
          </button>
          <input
            placeholder={t(locale, "estimatorName")}
            value={approver}
            onChange={(e) => setApprover(e.target.value)}
          />
        </div>
        {canonical.map((page) => (
          <div
            key={page.id}
            style={{ borderTop: "1px solid var(--line)", padding: "10px 0" }}
          >
            <strong>{page.topic}</strong>{" "}
            <span
              className="chip"
              style={{ color: page.status === "approved" ? "var(--ok)" : "var(--mut)" }}
            >
              {page.status} · v{page.version}
            </span>
            {page.stale && (
              <span className="chip" style={{ color: "var(--warn, var(--crit))", marginLeft: 6 }}>
                ⚠ {t(locale, "staleSource")}
              </span>
            )}
            <p className="muted" style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
              {page.body.slice(0, 400)}
            </p>
            {page.status !== "approved" && (
              <button
                disabled={busy || !approver.trim()}
                onClick={() => run(() => api.approveCanonical(page.id, approver.trim()))}
              >
                {t(locale, "approve")}
              </button>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
