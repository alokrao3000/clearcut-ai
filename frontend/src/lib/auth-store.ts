/**
 * Where the session token lives on the client.
 *
 * `localStorage`, which is a real trade-off worth stating: a token readable by JavaScript is
 * a token an XSS bug can steal. An httpOnly cookie would be safer, but the API issues bearer
 * tokens and cookies would need CSRF handling of their own. The mitigations that do apply
 * are on the server — sessions are revocable, expire in 14 days, and a role change or
 * password change ends them immediately.
 *
 * Kept out of React state deliberately: `api.ts` reads it on every request, and it has to be
 * readable from module scope rather than from a hook.
 */

const TOKEN_KEY = "clearcut.token";

type Listener = () => void;

const listeners = new Set<Listener>();
let cached: string | null = null;
let loaded = false;

function read(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private mode, blocked site data, or a sandboxed iframe. Treat as signed out rather
    // than crashing the whole app on a storage exception.
    return null;
  }
}

export function getToken(): string | null {
  if (!loaded) {
    cached = read();
    loaded = true;
  }
  return cached;
}

export function setToken(token: string | null) {
  cached = token;
  loaded = true;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage is unavailable; the token still works for this tab via `cached`.
  }
  listeners.forEach((fn) => fn());
}

export function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Lets React render the signed-in/out state without owning the token. */
export function getSnapshot() {
  return getToken();
}

export function getServerSnapshot(): string | null {
  return null;
}
