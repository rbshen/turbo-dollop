import { mutate as globalMutate, type ScopedMutator } from "swr";

import { navigate } from "@/lib/auth/navigate";
import { loginUrl } from "@/lib/auth/safeNext";

/** Drops every SWR entry without refetching, so one user's data never shows for the next (on login, logout and a 401).
 * Any key, mounted or not: the hooks refetch on their own when the next page mounts them. The app has one default cache, so the
 * global mutate is the default; a React caller inside a custom <SWRConfig> passes its own `useSWRConfig().mutate`. */
export async function clearClientCache(mutate: ScopedMutator = globalMutate): Promise<void> {
  await mutate(() => true, undefined, { revalidate: false });
}

let redirecting = false;

/** A request came back 401 (no valid session): drop the cached data and load /login?next=<this page>, once however many
 * requests fail together. Returns true when it is leaving the page (the caller must then not surface an error), false
 * when it did nothing: already on /login (no loop) or no browser. The full page load resets this flag. */
export function redirectToLogin(): boolean {
  if (typeof window === "undefined") return false;
  const { pathname, search } = window.location;
  if (pathname === "/login" || pathname.startsWith("/login/")) return false;
  if (redirecting) return true;
  redirecting = true;
  void clearClientCache();
  navigate(loginUrl(pathname + search));
  return true;
}

/** Test seam: a new test starts with no redirect in flight. */
export function resetRedirectGuardForTests(): void {
  redirecting = false;
}
