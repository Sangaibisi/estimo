/** Session state for the browser (S15-1).
 *
 * The session token lives in localStorage rather than a cookie because the API is a
 * separate origin from the app and is called with `fetch` from the client — a
 * cookie would need CORS credentials plus CSRF protection to buy back exactly what
 * an explicit Authorization header gives for free.
 *
 * Everything here is a plain module with a change event rather than a React context
 * provider, so `lib/api.ts` — which is not a component — can read the token on every
 * request without importing React.
 */

export const TOKEN_KEY = "estimo-session";
export const TENANT_KEY = "estimo-acting-tenant";
export const SESSION_EVENT = "estimo-session-change";

export type Role = "platform_admin" | "project_owner" | "user";

export interface SessionUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  can_sign: boolean;
  is_active: boolean;
  tenant_id: string;
  tenant_name?: string | null;
  acl_keys?: string[] | null;
  last_login_at?: string | null;
}

export function authToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(SESSION_EVENT));
}

/** The workspace a platform admin is currently acting inside. Ignored by the API
 * for every other role, so it is safe to send unconditionally. */
export function actingTenant(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TENANT_KEY);
}

export function setActingTenant(tenant: string | null): void {
  if (typeof window === "undefined") return;
  if (tenant) window.localStorage.setItem(TENANT_KEY, tenant);
  else window.localStorage.removeItem(TENANT_KEY);
  window.dispatchEvent(new Event(SESSION_EVENT));
}

/** Sign out locally. There is no server call: the token is stateless and short-
 * lived, and the revocation path that matters (deactivation, password change) is
 * the administrator's, not this button's. */
export function signOut(): void {
  setActingTenant(null);
  setAuthToken(null);
}

export function canShapeMap(role: Role | null | undefined): boolean {
  return role === "platform_admin" || role === "project_owner";
}

export const ROLE_LABELS: Record<Role, string> = {
  platform_admin: "Platform admin",
  project_owner: "Project owner",
  user: "User",
};
