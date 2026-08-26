/**
 * Talking to the platform.
 *
 * The session is a cookie the browser holds; the CSRF token is a header this
 * module adds to anything that changes state. Unsafe methods without it are
 * refused before the session is even looked up (`app/api/deps.py`), so the
 * token is kept here rather than remembered at each call site.
 */

const CSRF_HEADER = "x-csrf-token";
const CSRF_STORAGE_KEY = "hba.csrf";

/** A refusal from the platform, carrying what it said and what to do. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** Signed out, or the session expired while the tab sat open. */
  get isSignedOut(): boolean {
    return this.status === 401;
  }

  /** Signed in, but this account may not do that (§6.5). */
  get isRefused(): boolean {
    return this.status === 403;
  }
}

function readToken(): string | null {
  try {
    return sessionStorage.getItem(CSRF_STORAGE_KEY);
  } catch {
    // Private windows and locked-down browsers throw on access rather than
    // returning nothing. A missing token means the next write is refused and
    // the person signs in again, which is the right outcome either way.
    return null;
  }
}

export function rememberToken(token: string): void {
  try {
    sessionStorage.setItem(CSRF_STORAGE_KEY, token);
  } catch {
    /* see readToken */
  }
}

export function forgetToken(): void {
  try {
    sessionStorage.removeItem(CSRF_STORAGE_KEY);
  } catch {
    /* see readToken */
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";

  if (method !== "GET") {
    const token = readToken();
    if (token) headers[CSRF_HEADER] = token;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    // Same origin: FastAPI serves this bundle, so the cookie rides along.
    credentials: "same-origin",
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    // FastAPI puts the readable message in `detail`. Those messages are
    // written for a person — "Nour's 2026-08 cannot be approved: …" — so they
    // are shown as they are rather than replaced with something generic.
    const detail =
      payload && typeof payload.detail === "string"
        ? payload.detail
        : `The platform returned ${response.status}.`;
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
};

/**
 * Who is signed in.
 *
 * The shape mirrors `/api/auth/me` exactly - `actor` plus the permissions that
 * account holds. An earlier version of this file flattened it, guessed at the
 * fields, and rendered a blank page the first time somebody signed in. The
 * server's shape wins; this is a transcription, not an interpretation.
 */
export type Actor = {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
};

export type Session = {
  actor: Actor;
  /** §6.5 and §5.1. What this account may do, from the server. */
  permissions: string[];
};

/**
 * Whether this account may do something.
 *
 * Used to **not offer** an action rather than to offer it and let the request
 * fail with a 403. A button that refuses when pressed teaches somebody that
 * the tool is unreliable; a button that is not there teaches them the shape of
 * their job.
 *
 * The server checks again regardless - this hides, it does not protect.
 */
export function can(session: Session | null, permission: string): boolean {
  return session?.permissions.includes(permission) ?? false;
}

export async function currentUser(): Promise<Session | null> {
  try {
    return await api.get<Session>("/api/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.isSignedOut) return null;
    throw error;
  }
}

export async function signIn(
  email: string,
  password: string,
): Promise<Session> {
  const result = await api.post<{ csrf: string; actor: Actor }>(
    "/api/auth/login",
    { email, password },
  );
  rememberToken(result.csrf);
  // Login returns the actor; `me` also returns the permissions. Asking once
  // more keeps one source of truth for what this account may do, rather than
  // two shapes that can disagree.
  const session = await currentUser();
  if (session === null) {
    throw new ApiError(401, "Signed in, but the session did not stick.");
  }
  return session;
}

export async function signOut(): Promise<void> {
  try {
    await api.post("/api/auth/logout");
  } finally {
    // Forget locally even if the request failed. A stale token the server no
    // longer honours is worse than none: it makes every later write fail in a
    // way that looks like a bug rather than a sign-out.
    forgetToken();
  }
}
