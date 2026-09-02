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

/** The CSRF cookie the server sets beside the session. Readable on purpose. */
const CSRF_COOKIE = "hba_csrf";

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const entry = part.trim();
    if (entry.startsWith(prefix)) {
      return decodeURIComponent(entry.slice(prefix.length)) || null;
    }
  }
  return null;
}

/**
 * The token that proves a write came from this page.
 *
 * **The cookie first, and it is the one that matters.** `sessionStorage` is
 * emptied when the tab closes while the session cookie lives twelve hours, so
 * a returning tab had a live session and no token: every read worked, the
 * interface showed a signed-in administrator, and every write failed saying
 * authentication was required.
 *
 * The storage copy stays as a fallback for the one case the cookie cannot
 * cover — a browser configured to refuse cookies set on a response it is
 * already showing — and costs nothing when it is not needed.
 */
function readToken(): string | null {
  const fromCookie = readCookie(CSRF_COOKIE);
  if (fromCookie) return fromCookie;
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

/**
 * A file, sent as multipart rather than JSON.
 *
 * Separate from `request` because the body must not be stringified and the
 * content-type must be left alone — the browser sets it, including the
 * boundary, and overriding it produces a request the server cannot parse.
 */
async function upload<T>(path: string, file: File): Promise<T> {
  const headers: Record<string, string> = {};
  const token = readToken();
  if (token) headers[CSRF_HEADER] = token;

  const form = new FormData();
  form.append("file", file);

  const response = await fetch(path, {
    method: "POST",
    headers,
    body: form,
    credentials: "same-origin",
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
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
  upload,
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

/** Where the platform is in time, decided by the server and not the browser. */
export type Platform = {
  /**
   * The month a screen opens on. Usually this month; before go-live, the
   * go-live month — an empty August is not a useful first impression when the
   * platform starts in September.
   */
  working_month: string;
  /** The first month the platform is responsible for. Null until chosen. */
  go_live_month: string | null;
};

export type Session = {
  actor: Actor;
  /** §6.5 and §5.1. What this account may do, from the server. */
  permissions: string[];
  platform: Platform;
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

/**
 * Turn an invitation into an account, and sign the new person straight in.
 *
 * Mirrors `signIn` deliberately: the server's accept endpoint already
 * returns a live session (§13's "invited, accepted, and inside the tool in
 * one step"), so the same "ask `/me` once more for the permission list"
 * pattern applies here too.
 */
/**
 * Is this invitation link still good, and whose is it?
 *
 * Called when the page opens, not when the form is submitted. A withdrawn or
 * lapsed link used to render the whole form and refuse only at the end, after
 * somebody had chosen a name and a password.
 */
export async function previewInvitation(
  token: string,
): Promise<{ email: string; role: string }> {
  return api.get<{ email: string; role: string }>(
    `/api/auth/invitations/preview?token=${encodeURIComponent(token)}`,
  );
}

/**
 * How strong a password is, and why it might be refused.
 *
 * Asked of the server rather than worked out here. The rules would otherwise
 * exist twice, and the day the two drifted the symptom would be a green bar
 * over a password the server rejects - a screen telling somebody they are
 * fine while the button does not work.
 */
export async function checkPassword(
  password: string,
  personal: { email?: string; name?: string } = {},
): Promise<{ strength: number; problem: string | null; minimum: number }> {
  return api.post<{ strength: number; problem: string | null; minimum: number }>(
    "/api/auth/password-quality",
    { password, email: personal.email ?? "", name: personal.name ?? "" },
  );
}

/** Ask for a reset link. Answers the same way whether or not the account
 *  exists, so this can never be used to ask who is on the programme. */
export async function requestPasswordReset(email: string): Promise<void> {
  await api.post("/api/auth/password-reset/request", { email });
}

/** Whose reset link this is, checked when the page opens rather than when the
 *  form is submitted. */
export async function previewPasswordReset(
  token: string,
): Promise<{ email: string }> {
  return api.get<{ email: string }>(
    `/api/auth/password-reset/preview?token=${encodeURIComponent(token)}`,
  );
}

export async function completePasswordReset(
  token: string,
  password: string,
): Promise<Session> {
  const result = await api.post<{ csrf: string; actor: Actor }>(
    "/api/auth/password-reset",
    { token, password },
  );
  rememberToken(result.csrf);

  const session = await currentUser();
  if (session === null) {
    throw new ApiError(401, "Password changed, but the session did not stick.");
  }
  return session;
}

export async function acceptInvitation(
  token: string,
  password: string,
): Promise<Session> {
  const result = await api.post<{ csrf: string; actor: Actor }>(
    "/api/auth/invitations/accept",
    { token, password },
  );
  rememberToken(result.csrf);

  const session = await currentUser();
  if (session === null) {
    throw new ApiError(401, "Accepted, but the session did not stick.");
  }
  return session;
}

/**
 * Sign out, and end up signed out either way.
 *
 * **Never throws.** It used to: the logout call needs a CSRF token like any
 * other write, and when the token was missing it failed with a 401 — so the
 * navigation that was waiting on it never ran and the button appeared to do
 * nothing at all. Being unable to *tell* the server is not a reason to leave
 * somebody sitting in a session they asked to leave.
 *
 * The local half always happens. The cookies are cleared by the server's
 * response when it answers, and by the browser when they expire when it does
 * not.
 */
/**
 * Sign out, and land on the sign-in screen with nothing left over.
 *
 * **A full document load, deliberately.** Signing out with a client-side
 * navigation left the session in React state: the route guard saw somebody
 * signed in, sent them to the Overview, and the Overview asked the server a
 * question it now answered with 401. The screen read "Authentication
 * required" under a full sidebar, with the person's name still in the corner,
 * and only a refresh got them to the sign-in page.
 *
 * The server had done its part correctly. The application simply never told
 * itself.
 *
 * Reloading makes that impossible rather than unlikely: every piece of state
 * is re-derived from the server, so there is nothing left to be stale. It
 * costs a page load on the one action where nobody minds waiting, and it
 * removes a whole class of "the screen and the session disagree" bugs instead
 * of fixing one instance of it.
 *
 * It also has to be the *only* way out, which is why the navigation lives here
 * rather than at each call site. Two screens each doing their own version is
 * how one of them forgets.
 */
export async function signOutAndLeave(): Promise<void> {
  await signOut();
  // `replace`, so Back does not return to a page that no longer has a session.
  window.location.replace("/sign-in");
}

export async function signOut(): Promise<void> {
  try {
    await api.post("/api/auth/logout");
  } catch {
    // Recorded nowhere on purpose: there is nothing the person can do about
    // it, and the outcome they asked for still happens.
  } finally {
    // Forget locally regardless. A stale token the server no longer honours is
    // worse than none: it makes every later write fail in a way that looks
    // like a bug rather than a sign-out.
    forgetToken();
  }
}
