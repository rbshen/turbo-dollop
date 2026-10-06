"use client";

import { useRecomputeStatus } from "@/lib/hooks/useScoreWeights";

/** The score recompute's state in one line, for the Settings sections whose save starts one (Score weighting, Economic moat points):
 * "Recomputing scores, N of M" while it runs, the reason when the last run failed (until a later run succeeds), and how many tickers
 * could not be scored when a run finished with some. Nothing otherwise. */
export function RecomputeStatusLine() {
  const { run, running } = useRecomputeStatus();
  if (!run) return null;
  if (running) {
    return (
      <p role="status" className="mt-4 text-sm text-text-secondary" data-testid="recompute-status">
        Recomputing scores, {run.processed} of {run.total}
      </p>
    );
  }
  if (run.state === "failed") {
    return (
      <p role="alert" className="mt-4 max-w-xl text-sm text-negative" data-testid="recompute-status">
        The last score recompute failed: {run.error ?? "unknown error"} Your settings are saved, but stored scores may still be on the
        previous values until you run Recompute all scores on the Stocks Screener.
      </p>
    );
  }
  if (run.failed > 0) {
    return (
      <p className="mt-4 text-xs text-text-tertiary" data-testid="recompute-status">
        The last score recompute finished; {run.failed} {run.failed === 1 ? "ticker" : "tickers"} could not be scored.
      </p>
    );
  }
  return null;
}
