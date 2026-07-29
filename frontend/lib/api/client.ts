const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
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
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON or empty error body -- no detail to add.
    }
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}${detail ? ` - ${detail}` : ""}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

export function apiFetch<T>(path: string): Promise<T> {
  return request<T>(path);
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
