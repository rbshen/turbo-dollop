"use client";

import { AdminOnly } from "@/components/auth/AdminOnly";
import type { AnchorHeadroomOut, WarrenWatchOut } from "@/lib/api/types";
import { useWarrenWatch } from "@/lib/hooks/useWarrenWatch";
import { fmtDay } from "@/lib/technicalIdeas";
import { cn } from "@/lib/utils";

interface ViewProps {
  headroom: AnchorHeadroomOut;
}

// The two levels reuse the app's existing notice boxes: warn (DataQualityNote) and negative (FmpHealthSummaryCard) text on a tinted, bordered box.
const TONE: Record<AnchorHeadroomOut["level"], string> = {
  warning: "border-warn/40 bg-warn/10 text-warn",
  urgent: "border-negative/40 bg-negative/10 text-negative",
};

// Drawn only for an admin and only at warning or urgent (the backend sends nothing otherwise). Not dismissable: it clears itself when the anchor is
// moved and the headroom is back above 300 days (docs/specs/warren-signals-page.md, "Anchor headroom and re-anchor runbook").
export function AnchorHeadroomBannerView({ headroom }: ViewProps) {
  const urgent = headroom.level === "urgent";
  return (
    <div
      role={urgent ? "alert" : "status"}
      aria-label={urgent ? "Warren replay start: urgent" : "Warren replay start: warning"}
      className={cn("space-y-1 rounded-md border p-3 text-sm", TONE[headroom.level])}
    >
      <p className="font-medium">
        {urgent ? "Urgent: the" : "The"} Warren replay start date is running out of warm-up history.
      </p>
      <p>
        The watch table replays every ticker from {fmtDay(headroom.anchor.slice(0, 10))} {headroom.anchor.slice(11, 16)} ET and has {headroom.days} days of cached history before it (a warning below 300
        days, urgent below 270, the hard deadline at 180). It {urgent ? "became" : "becomes"} urgent on {fmtDay(headroom.urgent_date)}; the hard deadline is{" "}
        {fmtDay(headroom.deadline_date)}.
      </p>
      <p>Re-anchor: see the runbook in docs/specs/warren-signals-page.md.</p>
    </div>
  );
}

interface Props {
  // Test seam: the banner reads the watch table's own resource (useWarrenWatch, the same SWR key as the table) unless a test passes a stand-in.
  useData?: () => { data?: WarrenWatchOut };
}

export function AnchorHeadroomBanner({ useData = useWarrenWatch }: Props) {
  const { data } = useData();
  const headroom = data?.anchor_headroom;
  if (!headroom) return null;
  return (
    <AdminOnly>
      <AnchorHeadroomBannerView headroom={headroom} />
    </AdminOnly>
  );
}
