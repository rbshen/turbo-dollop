"use client";

import { useFmpStatus } from "@/lib/hooks/useFmpStatus";

// Deliberately no dismiss/hide state, not even in-memory -- this is a pure
// function of the fetched flag, so it necessarily reappears on every
// load/navigation while FMP is paused, which is the whole point (can't be
// missed after a session gap). No extra polling beyond SWR's own default
// revalidate-on-focus: the flag only changes via a backend restart (see
// FmpStatusOut), never mid-session, so anything fancier is unneeded.
export function FmpPausedBanner() {
  const { data } = useFmpStatus();

  if (!data || data.enabled) return null;

  return (
    <div className="border-b border-warn/40 bg-warn/10 px-4 py-2 text-center text-sm font-medium text-warn">
      FMP is currently paused — running on cached data only. Some data may be stale, and new-ticker search and manual
      refresh are unavailable.
    </div>
  );
}
