// OAuth2 token session helpers. The access/refresh tokens come from the
// store's own authorization-code flow (see /callback).

export interface AuthSession {
  access_token: string;
  refresh_token: string;
  customer_id: string;
  username: string;
}

const KEY = "scs_auth_session";

export function loadSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthSession;
  } catch {
    return null;
  }
}

export function saveSession(session: AuthSession) {
  localStorage.setItem(KEY, JSON.stringify(session));
}

export function clearSession() {
  localStorage.removeItem(KEY);
}

// fetch wrapper that attaches the Bearer token to /api calls.
export async function api(path: string, init: RequestInit = {}) {
  const session = loadSession();
  const headers = new Headers(init.headers || {});
  if (session) headers.set("Authorization", `Bearer ${session.access_token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail}`);
  }
  return response;
}

// Random state for the OAuth2 authorization request.
export function randomState(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
