/** Where a sign-in goes when there is no (valid) `next` parameter. */
export const DEFAULT_AFTER_LOGIN = "/screener";

const ORIGIN = "http://same-origin.invalid";

/** The `next` parameter of /login as a same-origin relative path, or null. Only a path that starts with a single "/" is
 * accepted: a scheme ("http://evil.com", "javascript:"), a protocol-relative "//evil.com", any backslash (browsers read
 * "/\evil.com" as "//evil.com") and any control character (a browser drops a tab or newline inside a URL, so "/\t/evil.com"
 * would become "//evil.com") are all refused. /login itself is refused too, so a sign-in can never bounce back to the form.
 * The final check parses the path against a throwaway origin and requires it to stay there. */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 2048) return null;
  if (raw[0] !== "/" || raw[1] === "/" || raw[1] === "\\") return null;
  if (/[\\\u0000-\u001f\u007f]/.test(raw)) return null;
  let url: URL;
  try {
    url = new URL(raw, ORIGIN);
  } catch {
    return null;
  }
  if (url.origin !== ORIGIN) return null;
  if (url.pathname === "/login" || url.pathname.startsWith("/login/")) return null;
  return raw;
}

/** `/login?next=<current page>` for a signed-out visitor; a current page that is not a safe path (or is /login) gives plain `/login`. */
export function loginUrl(current: string | null | undefined): string {
  const next = safeNextPath(current);
  return next ? `/login?next=${encodeURIComponent(next)}` : "/login";
}
