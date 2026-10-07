"use client";

import { useScoreWeights } from "@/lib/hooks/useScoreWeights";
import { staleWeightsCount, staleWeightsMessage } from "@/lib/scoreWeightsStale";
import type { TickerScoreOut } from "@/lib/api/types";

/** A muted line under the Screener header while stored rows are still on older score weights or an older Overall formula (a recompute is running, or failed, or
 * has not been run since the weights, the Narrow moat multiplier or the formula changed). Informational only: it never changes a row, a sort or a filter. Renders nothing when
 * every listed row is current. */
export function StaleWeightsNote({ rows }: { rows: TickerScoreOut[] | undefined }) {
  const { data } = useScoreWeights();
  const count = staleWeightsCount(rows, data?.weights_version, data?.formula_version);
  if (count === 0) return null;
  const running = data?.recompute?.state === "running";
  return (
    <p className="text-xs text-text-tertiary" data-testid="stale-weights-note">
      {staleWeightsMessage(count)}
      {running ? " (recomputing now)" : ""}.
    </p>
  );
}
