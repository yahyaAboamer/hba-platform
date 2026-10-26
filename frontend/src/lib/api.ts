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

/**
 * A model's portal, opened by staff to look at - read only (ADR 0064).
 *
 * Her screens ask for `/api/me/...` as they always do; while a preview is on,
 * this module sends those reads to `/api/affiliates/{id}/portal/...` instead,
 * which answers with the same handlers for the model named. **Every write is
 * refused here, before it is sent**, and the server has no write route for the
 * preview either, so a control a screen forgot to hide still changes nothing.
 *
 * Module-wide on purpose: the preview runs in a frame of its own, a separate
 * page in which everything is the preview.
 */
let previewBase: string | null = null;

export const PREVIEW_READ_ONLY =
  "This is a read-only preview of her portal. Nothing can be changed from here.";

/** Her full payout details stay shortened in the preview: there is no route. */
const NOT_IN_PREVIEW = new Set(["/api/me/payout-destination"]);

export function startPortalPreview(affiliateId: number): void {
  previewBase = `/api/affiliates/${affiliateId}/portal`;
}

export function stopPortalPreview(): void {
  previewBase = null;
}

/** Whether this page is staff looking at a model's portal. */
export function isPortalPreview(): boolean {
  return previewBase !== null;
}

/**
 * Where one of her reads goes: unchanged normally, the preview's address in a
 * preview. Exported for the one read the browser makes by itself - a transfer
 * screenshot's `<img src>`. `tests/test_reachability.py` mirrors this mapping.
 */
export function portalPath(path: string): string {
  if (previewBase === null) return path;
  if (path === "/api/applications/mine") return `${previewBase}/application`;
  if (path === "/api/me" || path.startsWith("/api/me/") || path.startsWith("/api/me?")) {
    return previewBase + path.slice("/api/me".length);
  }
  return path;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  if (previewBase !== null) {
    if (method !== "GET" || NOT_IN_PREVIEW.has(path.split("?")[0])) {
      throw new ApiError(403, PREVIEW_READ_ONLY);
    }
    path = portalPath(path);
  }

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
 *
 * `options` is for a route that names its file field differently, or takes
 * other fields beside it: the inbox's `upload`, with a caption (ADR 0059).
 */
async function upload<T>(
  path: string,
  file: File | Blob,
  options: { field?: string; filename?: string; fields?: Record<string, string> } = {},
): Promise<T> {
  if (previewBase !== null) throw new ApiError(403, PREVIEW_READ_ONLY);

  const headers: Record<string, string> = {};
  const token = readToken();
  if (token) headers[CSRF_HEADER] = token;

  const form = new FormData();
  for (const [name, value] of Object.entries(options.fields ?? {})) form.append(name, value);
  if (options.filename) form.append(options.field ?? "file", file, options.filename);
  else form.append(options.field ?? "file", file);

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
  /**
   * **The platform's only DELETE**, added in Phase 03C for withdrawing a
   * feature request (W09).
   *
   * Named `del` because `delete` is a reserved word. Deliberately not used for
   * anything financial: nothing this platform records about money is ever
   * removed - approvals, transfers, allocations and destinations are
   * append-only and guarded by database triggers. A request to feature a
   * garment is not that, and withdrawing one should not leave a tombstone
   * somebody has to read past.
   */
  del: <T>(path: string) => request<T>("DELETE", path),
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
  /**
   * Every role held now, widest first (ADR 0067: a person may hold several).
   * For naming the person only - what a screen shows is decided by
   * `permissions`, never by a role's name.
   */
  roles: string[];
  /** Holds any staff role. */
  is_staff: boolean;
  /** Owns a model's record: what makes somebody a model (ADR 0006). */
  is_model: boolean;
  /**
   * Two-step sign-in for this account (Batch 1.3), sent inside `actor` by
   * the server. Optional only so an older answer still reads.
   */
  two_step?: TwoStepState;
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
  /** The first month anything can be known in (`PLATFORM_START_MONTH`). */
  start_month: string;
};

export type Session = {
  actor: Actor;
  /** §6.5 and §5.1. What this account may do, from the server. */
  permissions: string[];
  platform: Platform;
};

export type TwoStepState = {
  enabled: boolean;
  /** Their access needs it (an admin, or somebody who approves or pays). */
  required: boolean;
  /** Required, not on yet, and the owner has switched enforcing on. */
  must_set_up: boolean;
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

/**
 * The words under a person's name: the role they are known by, the widest
 * they hold (the server lists them widest first). Words only - nothing is
 * decided by it.
 */
export function roleLabel(actor: Actor): string {
  return (actor.roles[0] ?? "").replace(/_/g, " ");
}

/**
 * Which set of screens a person gets (ADR 0067, decision 9), asked of what
 * they may do and never of a role's name:
 *
 * - **portal**: no staff permission at all - a model, who reaches her portal
 *   by owning her record (`is_model`), or somebody invited to become one who
 *   has not applied yet;
 * - **operations**: Operations without the affiliate side (ADR 0057), with
 *   the Inbox too when they hold it;
 * - **inbox**: the Inbox and nothing else (ADR 0059);
 * - **affiliates**: everyone else - the affiliate dashboard, with Operations
 *   and the Inbox beside it for whoever holds them.
 */
export type Desk = "portal" | "operations" | "inbox" | "affiliates";

export function deskFor(session: Session): Desk {
  if (session.permissions.length === 0) return "portal";
  if (can(session, "affiliates.view")) return "affiliates";
  if (can(session, "order_ops.view")) return "operations";
  if (can(session, "inbox.use")) return "inbox";
  return "affiliates";
}

export async function currentUser(): Promise<Session | null> {
  try {
    return await api.get<Session>("/api/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.isSignedOut) return null;
    throw error;
  }
}

/**
 * What the password step answered: a session, or "now the code".
 *
 * `pending` is the one-use token the second step hands back; it is never
 * stored, only kept in the sign-in screen's state for five minutes.
 */
export type SignInResult =
  | { kind: "session"; session: Session }
  | { kind: "code"; pending: string; expiresIn: number };

async function sessionAfterLogin(csrf: string): Promise<Session> {
  rememberToken(csrf);
  // Login returns the actor; `me` also returns the permissions. Asking once
  // more keeps one source of truth for what this account may do, rather than
  // two shapes that can disagree.
  const session = await currentUser();
  if (session === null) {
    throw new ApiError(401, "Signed in, but the session did not stick.");
  }
  return session;
}

export async function signIn(
  email: string,
  password: string,
): Promise<SignInResult> {
  const result = await api.post<
    | { csrf: string; actor: Actor }
    | { two_step: "code"; pending: string; expires_in: number }
  >("/api/auth/login", { email, password });
  if ("two_step" in result) {
    return { kind: "code", pending: result.pending, expiresIn: result.expires_in };
  }
  return { kind: "session", session: await sessionAfterLogin(result.csrf) };
}

/** The second step: an authenticator code or a recovery code. */
export async function signInWithCode(
  pending: string,
  code: string,
): Promise<{ session: Session; recoveryCodesLeft: number | null }> {
  const result = await api.post<{
    csrf: string;
    actor: Actor;
    recovery_codes_left?: number;
  }>("/api/auth/login/two-step", { pending, code });
  return {
    session: await sessionAfterLogin(result.csrf),
    recoveryCodesLeft: result.recovery_codes_left ?? null,
  };
}

// ── Two-step sign-in, and where somebody is signed in (Batch 1.3) ──────────

export type TwoStepStatus = TwoStepState & {
  enabled_at: string | null;
  recovery_codes_left: number;
};

export type TwoStepStart = {
  secret: string;
  otpauth_uri: string;
  /** Server-made SVG; shown as an image, never inserted as markup. */
  qr_svg: string;
};

export type DeviceSession = {
  id: number;
  device: string;
  ip_address: string | null;
  created_at: string;
  last_seen_at: string;
  current: boolean;
};

export const twoStep = {
  status: () => api.get<TwoStepStatus>("/api/auth/two-step"),
  start: (password: string) =>
    api.post<TwoStepStart>("/api/auth/two-step/start", { password }),
  confirm: (code: string) =>
    api.post<{ recovery_codes: string[] }>("/api/auth/two-step/confirm", { code }),
  newRecoveryCodes: (code: string) =>
    api.post<{ recovery_codes: string[] }>("/api/auth/two-step/recovery-codes", { code }),
  turnOff: (code: string) =>
    api.post<{ enabled: false }>("/api/auth/two-step/turn-off", { code }),
};

export const devices = {
  mine: () => api.get<{ sessions: DeviceSession[] }>("/api/auth/sessions"),
  endOne: (id: number) => api.post<{ ended: boolean }>(`/api/auth/sessions/${id}/end`),
  endOthers: () => api.post<{ ended: number }>("/api/auth/sessions/end-others"),
  of: (staffId: number) =>
    api.get<{ sessions: DeviceSession[] }>(`/api/staff/${staffId}/sessions`),
  endAllOf: (staffId: number) =>
    api.post<{ ended: number }>(`/api/staff/${staffId}/sessions/end-all`),
  resetTwoStepOf: (staffId: number, code: string) =>
    api.post<{ enabled: false }>(`/api/staff/${staffId}/two-step/reset`, { code }),
};

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
): Promise<SignInResult> {
  // Somebody with two-step on is not signed in by a reset: the code is still
  // asked, as at sign-in, or reading the mailbox would be enough.
  const result = await api.post<
    | { csrf: string; actor: Actor }
    | { two_step: "code"; pending: string; expires_in: number }
  >("/api/auth/password-reset", { token, password });
  if ("two_step" in result) {
    return { kind: "code", pending: result.pending, expiresIn: result.expires_in };
  }
  rememberToken(result.csrf);

  const session = await currentUser();
  if (session === null) {
    throw new ApiError(401, "Password changed, but the session did not stick.");
  }
  return { kind: "session", session };
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
