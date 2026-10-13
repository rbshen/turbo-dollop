import { mutate as globalMutate, type ScopedMutator } from "swr";

/** Drops every SWR entry without refetching, so one user's data never shows for the next (on login, logout and a 401).
 * Any key, mounted or not: the hooks refetch on their own when the next page mounts them. The app has one default cache, so the
 * global mutate is the default; a React caller inside a custom <SWRConfig> passes its own `useSWRConfig().mutate`. */
export async function clearClientCache(mutate: ScopedMutator = globalMutate): Promise<void> {
  await mutate(() => true, undefined, { revalidate: false });
}

/** A full page load, not a router push: it also throws away every in-memory module and component state. The one place
 * the app navigates for auth, so tests replace it (jsdom has no navigation). */
export function navigate(url: string): void {
  window.location.assign(url);
}
