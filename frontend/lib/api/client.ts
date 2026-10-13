import { redirectToLogin } from "@/lib/auth/session";

const BASE = "/api";

// FastAPI returns a string `detail` for an HTTPException and, for a request
// validation failure (422), a LIST: [{type, loc: ["body", "<field>"], msg,
// input, ctx}, ...]. Both become one readable string; anything else has none.
function formatDetail(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return undefined;
  const parts = detail.flatMap((item): string[] => {
    if (typeof item?.msg !== "string") return [];
    const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : undefined;
    return [typeof field === "string" ? `${field}: ${item.msg}` : item.msg];
  });
  return parts.length > 0 ? parts.join("; ") : undefined;
}

/** What every failed request throws. `message` keeps the original "METHOD path failed: STATUS - detail" text (callers
 * match on it and show `errorDetail`); `status`, `detail` and `retryAfter` (seconds, from a 429's Retry-After header)
 * are there for the callers that branch on the outcome (the login form, the viewer's "not available" state). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The HTTP status of a failed request, or undefined for any other error. */
export function errorStatus(e: unknown): number | undefined {
  return e instanceof ApiError ? e.status : undefined;
}

/** The line a 403 shows in place of the backend's "Admin access required": what it means for the person looking at it. */
export const ADMIN_REQUIRED_MESSAGE = "Admin access required — this account is view-only.";

// A 401 on these is an answer, not a lost session: a wrong password, and a sign-out of a session that is already gone.
const NO_LOGIN_REDIRECT = new Set(["/auth/login", "/auth/logout"]);

// Sent on every request. The backend (core/request_guard.py) rejects a write that has neither an allowed Origin nor
// this header; a cross-site HTML form cannot set it, so it marks the request as coming from this app's own code.
export const REQUEST_HEADER = "X-Fathom-Request";

// The one place the app calls fetch (apart from this file's own tests): every request carries REQUEST_HEADER, and
// headers a caller passes are added to it instead of replacing it.
async function send(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", [REQUEST_HEADER]: "1", ...init?.headers },
  });
  if (res.status === 401 && !NO_LOGIN_REDIRECT.has(path) && redirectToLogin()) {
    // The session is gone and the page is being replaced by /login: settle nothing, so no caller shows an error (or a
    // toast) for a request whose page is about to disappear.
    return new Promise<never>(() => {});
  }
  if (!res.ok) {
    // Best-effort: surface the backend's own detail message (e.g. FastAPI's
    // HTTPException body) so callers can show real validation feedback
    // instead of a bare status code. Falls back to the plain message below
    // if the body isn't JSON or has no `detail` -- the "failed: {status}"
    // substring is always still present, so existing status-code checks
    // elsewhere (e.g. `.includes("409")`) keep working unchanged.
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = formatDetail(body?.detail);
    } catch {
      // Non-JSON or empty error body -- no detail to add.
    }
    // A viewer's write or admin-only read: say what it means, not the backend's bare "Admin access required".
    if (res.status === 403 && detail === "Admin access required") detail = ADMIN_REQUIRED_MESSAGE;
    const retryAfter = Number(res.headers?.get?.("Retry-After"));
    throw new ApiError(
      `${init?.method ?? "GET"} ${path} failed: ${res.status}${detail ? ` - ${detail}` : ""}`,
      res.status,
      detail,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    );
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

export function apiFetch<T>(path: string): Promise<T> {
  return request<T>(path);
}

// A file download (CSV, text): the response body as a Blob instead of parsed JSON.
export async function apiFetchBlob(path: string): Promise<Blob> {
  const res = await send(path);
  return res.blob();
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined });
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined });
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

// Extracts the " - <detail>" suffix request() appends above, so a caller
// can show the backend's own rejection message (e.g. a capacity cap or a
// duplicate-name 409) instead of a bare "Failed" label.
export function errorDetail(e: unknown): string | undefined {
  if (!(e instanceof Error)) return undefined;
  const idx = e.message.indexOf(" - ");
  return idx === -1 ? undefined : e.message.slice(idx + 3);
}
