/** A full page load, not a router push: it also throws away every in-memory module and component state. The one place
 * the app navigates for auth, in its own module so tests can replace it (jsdom has no navigation). */
export function navigate(url: string): void {
  window.location.assign(url);
}
