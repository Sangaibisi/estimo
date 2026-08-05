"use client";

/** Settings → Workspaces and People (S15-1), plus the first-run setup card.
 *
 * Everything here is platform-admin territory. The one exception is the setup card,
 * which appears exactly once in a deployment's life: while no account exists, the
 * API is still open, and someone has to close it.
 */

import { useCallback, useEffect, useState } from "react";
import { api, type TenantEntry } from "@/lib/api";
import { ROLE_LABELS, setAuthToken, type Role, type SessionUser } from "@/lib/auth";
import { useSession } from "@/components/Session";
import { BandHeader, Chip, Lbl, Mn, StatusChip } from "@/components/ui";

const ROLE_ORDER: Role[] = ["platform_admin", "project_owner", "user"];

const ROLE_HINTS: Record<Role, string> = {
  platform_admin: "Creates workspaces and accounts; configures connections and the gateway.",
  project_owner: "Creates projects and draws the repository map, plus everything a user does.",
  user: "Works the product: estimates, ledger, calibration, knowledge.",
};

export function SetupCard() {
  const session = useSession();
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [workspace, setWorkspace] = useState("Default workspace");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (session.accountsExist) return null;

  async function claim() {
    setBusy(true);
    setError(null);
    try {
      const created = await api.bootstrap({
        setup_token: token.trim(),
        email: email.trim(),
        name: name.trim(),
        password,
        workspace: workspace.trim(),
      });
      setAuthToken(created.token);
      window.location.reload();
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
      <BandHeader
        title="Claim this deployment"
        subtitle="Nobody has an account yet, so the API is still answering anonymous callers."
        right={<StatusChip status="warn">open</StatusChip>}
      />
      <div style={{ padding: "14px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 12.5, color: "var(--ink2)", textWrap: "pretty" }}>
          Creating the first platform admin closes the door for good. The setup token is
          printed in the API container log at startup (<Mn>one-time setup token is …</Mn>), or
          set by whoever deployed this as <Mn>ESTIMO_SETUP_TOKEN</Mn>.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <input
            placeholder="setup token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <input
            placeholder="workspace name"
            value={workspace}
            onChange={(event) => setWorkspace(event.target.value)}
          />
          <input
            placeholder="your name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <input
            type="email"
            autoComplete="username"
            placeholder="you@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <input
            type="password"
            autoComplete="new-password"
            placeholder="password — at least 10 characters"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <button
            type="button"
            className="btn p"
            style={{ justifyContent: "center" }}
            disabled={busy || !token.trim() || !email.trim() || !name.trim() || !password}
            onClick={claim}
          >
            {busy ? "Creating…" : "Create platform admin"}
          </button>
        </div>
        {error && (
          <div style={{ fontSize: 12, color: "var(--crit)" }} role="alert">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

export function AccountsAdmin() {
  const session = useSession();
  const [tenants, setTenants] = useState<TenantEntry[]>([]);
  const [users, setUsers] = useState<SessionUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const [showWorkspace, setShowWorkspace] = useState(false);

  const [draftName, setDraftName] = useState("");
  const [draftEmail, setDraftEmail] = useState("");
  const [draftPassword, setDraftPassword] = useState("");
  const [draftRole, setDraftRole] = useState<Role>("user");
  const [draftSign, setDraftSign] = useState(false);
  const [draftTenant, setDraftTenant] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");

  const refresh = useCallback(() => {
    Promise.all([api.listTenants(), api.listUsers()])
      .then(([tenantRows, userRows]) => {
        setTenants(tenantRows);
        setUsers(userRows);
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (session.role === "platform_admin") refresh();
  }, [session.role, refresh]);

  if (session.role !== "platform_admin") return null;

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

  const tenantName = (id: string) => tenants.find((tenant) => tenant.id === id)?.name ?? "—";

  return (
    <>
      {/* ---- Workspaces ---- */}
      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title="Workspaces"
          subtitle="Each workspace is an isolated tenant — its projects, maps and ledger are its own."
          right={
            <button
              type="button"
              className="btn glow"
              onClick={() => setShowWorkspace(!showWorkspace)}
            >
              {showWorkspace ? "Close" : "+ Workspace"}
            </button>
          }
        />
        {showWorkspace && (
          <div
            style={{
              display: "flex",
              gap: 8,
              padding: "14px 18px",
              borderBottom: "1px solid var(--line)",
              background: "oklch(0.19 0.016 300)",
            }}
          >
            <input
              style={{ flex: 1 }}
              placeholder="workspace name — e.g. Aurora Telecom"
              value={workspaceName}
              onChange={(event) => setWorkspaceName(event.target.value)}
            />
            <button
              type="button"
              className="btn p"
              disabled={busy || !workspaceName.trim()}
              onClick={() =>
                run(async () => {
                  await api.createTenant(workspaceName.trim());
                  setWorkspaceName("");
                  setShowWorkspace(false);
                })
              }
            >
              Create
            </button>
          </div>
        )}
        <table className="dt">
          <thead>
            <tr>
              <th>Workspace</th>
              <th style={{ width: 160 }}>Slug</th>
              <th style={{ width: 90 }}>People</th>
              <th style={{ width: 90 }}>Projects</th>
            </tr>
          </thead>
          <tbody>
            {tenants.map((tenant) => (
              <tr key={tenant.id}>
                <td>
                  {tenant.name}
                  {tenant.id === session.tenant && (
                    <Chip style={{ marginLeft: 8 }}>acting here</Chip>
                  )}
                </td>
                <td>
                  <Mn>{tenant.slug}</Mn>
                </td>
                <td className="num">{tenant.users}</td>
                <td className="num">{tenant.projects}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ---- People ---- */}
      <div className="card" style={{ overflow: "hidden", marginBottom: 16 }}>
        <BandHeader
          title="People"
          subtitle="Accounts are created here — there is no self-registration."
          right={
            <button type="button" className="btn glow" onClick={() => setShowInvite(!showInvite)}>
              {showInvite ? "Close" : "+ Person"}
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

        {showInvite && (
          <div
            style={{
              padding: "14px 18px",
              borderBottom: "1px solid var(--line)",
              background: "oklch(0.19 0.016 300)",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
              <input
                placeholder="full name"
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
              />
              <input
                type="email"
                placeholder="email"
                value={draftEmail}
                onChange={(event) => setDraftEmail(event.target.value)}
              />
              <input
                type="password"
                autoComplete="new-password"
                placeholder="initial password — 10+ characters"
                value={draftPassword}
                onChange={(event) => setDraftPassword(event.target.value)}
              />
              <select
                value={draftRole}
                onChange={(event) => setDraftRole(event.target.value as Role)}
              >
                {ROLE_ORDER.map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABELS[role]}
                  </option>
                ))}
              </select>
              <select
                value={draftTenant || session.tenant || ""}
                onChange={(event) => setDraftTenant(event.target.value)}
              >
                {tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </option>
                ))}
              </select>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12,
                  color: "var(--ink2)",
                }}
              >
                <input
                  type="checkbox"
                  checked={draftSign}
                  onChange={(event) => setDraftSign(event.target.checked)}
                  style={{ width: 14, height: 14, padding: 0 }}
                />
                may sign a Basis of Estimate
              </label>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 11.5, color: "var(--mut)", flex: 1, textWrap: "pretty" }}>
                {ROLE_HINTS[draftRole]}
              </span>
              <button
                type="button"
                className="btn p"
                disabled={busy || !draftName.trim() || !draftEmail.trim() || !draftPassword}
                onClick={() =>
                  run(async () => {
                    await api.createUser({
                      name: draftName.trim(),
                      email: draftEmail.trim(),
                      password: draftPassword,
                      role: draftRole,
                      can_sign: draftSign,
                      tenant_id: draftTenant || session.tenant,
                    });
                    setDraftName("");
                    setDraftEmail("");
                    setDraftPassword("");
                    setDraftSign(false);
                    setShowInvite(false);
                  })
                }
              >
                Create account
              </button>
            </div>
          </div>
        )}

        <table className="dt">
          <thead>
            <tr>
              <th>Person</th>
              <th style={{ width: 170 }}>Workspace</th>
              <th style={{ width: 170 }}>Role</th>
              <th style={{ width: 90 }}>Signs</th>
              <th style={{ width: 120 }}>State</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td>
                  <span style={{ display: "block", fontSize: 13 }}>{user.name}</span>
                  <Mn style={{ color: "var(--mut)" }}>{user.email}</Mn>
                </td>
                <td style={{ fontSize: 12, color: "var(--ink2)" }}>{tenantName(user.tenant_id)}</td>
                <td>
                  <select
                    value={user.role}
                    disabled={busy}
                    onChange={(event) =>
                      run(() => api.updateUser(user.id, { role: event.target.value }))
                    }
                    style={{ fontSize: 11.5, padding: "4px 7px" }}
                  >
                    {ROLE_ORDER.map((role) => (
                      <option key={role} value={role}>
                        {ROLE_LABELS[role]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={user.can_sign}
                    disabled={busy}
                    onChange={(event) =>
                      run(() => api.updateUser(user.id, { can_sign: event.target.checked }))
                    }
                    style={{ width: 14, height: 14, padding: 0 }}
                    aria-label={`${user.name} may sign`}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    style={{ padding: "4px 9px" }}
                    onClick={() =>
                      run(() => api.updateUser(user.id, { is_active: !user.is_active }))
                    }
                  >
                    {user.is_active ? "Deactivate" : "Reactivate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: "10px 18px" }}>
          <Lbl>
            Changing a role, workspace or password ends that person&apos;s open sessions
            immediately.
          </Lbl>
        </div>
      </div>
    </>
  );
}
