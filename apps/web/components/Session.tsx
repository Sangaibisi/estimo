"use client";

/** The session gate (S15-1): who is signed in, and what the app shows if nobody is.
 *
 * Three states, and the difference between the last two is the whole first-run
 * story:
 *  - signed in → the product;
 *  - accounts exist, nobody signed in → the login screen;
 *  - NO accounts anywhere → the deployment has never been claimed. The API is still
 *    open (its historical single-tenant behaviour), so the product renders, and the
 *    setup card in Settings is how someone closes the door.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import {
  SESSION_EVENT,
  setActingTenant,
  setAuthToken,
  signOut,
  type Role,
  type SessionUser,
} from "@/lib/auth";
import { LogoMark } from "@/components/icons";

interface SessionState {
  loading: boolean;
  authenticated: boolean;
  accountsExist: boolean;
  user: SessionUser | null;
  role: Role | null;
  tenant: string | null;
  refresh: () => void;
}

const SessionContext = createContext<SessionState>({
  loading: true,
  authenticated: false,
  accountsExist: false,
  user: null,
  role: null,
  tenant: null,
  refresh: () => {},
});

export function useSession(): SessionState {
  return useContext(SessionContext);
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Omit<SessionState, "refresh">>({
    loading: true,
    authenticated: false,
    accountsExist: false,
    user: null,
    role: null,
    tenant: null,
  });
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let live = true;
    api
      .me()
      .then((me) => {
        if (!live) return;
        setState({
          loading: false,
          authenticated: me.authenticated,
          accountsExist: me.accounts_exist,
          user: me.user,
          role: (me.role as Role | null) ?? null,
          tenant: me.tenant,
        });
      })
      .catch(() => {
        // A deployment we cannot reach is not a deployment we may assume is open.
        if (live) setState((s) => ({ ...s, loading: false, authenticated: false }));
      });
    return () => {
      live = false;
    };
  }, [tick]);

  // A 401 anywhere in the app clears the token and fires this event; the gate then
  // re-resolves and lands the person on the login screen instead of a wall of red.
  useEffect(() => {
    const onChange = () => refresh();
    window.addEventListener(SESSION_EVENT, onChange);
    return () => window.removeEventListener(SESSION_EVENT, onChange);
  }, [refresh]);

  const value = useMemo(() => ({ ...state, refresh }), [state, refresh]);

  if (state.loading) {
    return <Splash>Checking your session…</Splash>;
  }
  if (!state.authenticated && state.accountsExist) {
    return <LoginScreen onSignedIn={refresh} />;
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

function Splash({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--mut)",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        letterSpacing: "0.1em",
      }}
    >
      {children}
    </div>
  );
}

function LoginScreen({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await api.login(email, password);
      setActingTenant(null);
      setAuthToken(session.token);
      onSignedIn();
    } catch {
      // Deliberately not the server's wording: "invalid email or password" is the
      // only thing a sign-in form may say, or it becomes an account oracle.
      setError("That email and password combination did not work.");
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        background:
          "radial-gradient(120% 90% at 30% 0%, oklch(0.22 0.035 300) 0%, var(--bg) 62%)",
      }}
    >
      <form
        onSubmit={submit}
        className="card"
        style={{
          width: 380,
          padding: "26px 26px 22px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 4 }}>
          <LogoMark size={30} />
          <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em" }}>Estimo</span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                color: "var(--mut)",
                letterSpacing: "0.16em",
              }}
            >
              BASIS OF ESTIMATE
            </span>
          </span>
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <span className="lbl">Email</span>
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <span className="lbl">Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>

        {error && (
          <div
            role="alert"
            style={{
              fontSize: 12,
              color: "var(--crit)",
              border: "1px solid var(--crit)",
              background: "var(--crit-bg)",
              borderRadius: "var(--r)",
              padding: "8px 10px",
            }}
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          className="btn p"
          disabled={busy}
          style={{ justifyContent: "center", marginTop: 4 }}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <div style={{ fontSize: 11.5, color: "var(--mut)", textWrap: "pretty" }}>
          Accounts are created by a platform admin — there is no self-registration.
        </div>
      </form>
    </div>
  );
}

export { signOut };
