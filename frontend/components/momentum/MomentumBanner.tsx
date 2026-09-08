// Persistent, no-dismiss-state banner -- same bare-div convention as
// FmpPausedBanner/CronHealthBanner, but deliberately NOT their amber/red
// alarm styling: this isn't a problem to flag, just a standing disclaimer
// that reappears on every load (the point, per those two banners'
// precedent), styled muted-blue (the same brand token TopNav's own
// active-nav-item state already uses) so it doesn't read as an alert.
export function MomentumBanner() {
  return (
    <div className="border-b border-brand/30 bg-brand/10 px-4 py-2 text-center text-sm font-medium text-brand">
      Live price-momentum signal — not a fundamentals score, not investment advice.
    </div>
  );
}
