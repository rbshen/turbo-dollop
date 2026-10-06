import { Warning } from "@phosphor-icons/react";

import type { DataQualityFlag } from "@/lib/api/types";
import {
  RATIOS_FROM_FMP_MESSAGE,
  notLandedFlag,
  notLandedMessage,
  partialBalanceSheetFlag,
  partialBalanceSheetMessage,
  showsFmpRatiosNote,
} from "@/lib/dataQuality";

interface Props {
  flags: DataQualityFlag[] | undefined;
}

/** Warn box for a newest balance sheet the Analysis tab skipped (backend balance-sheet gate, helpers/balance_sheet_gate.py).
 * Same box as OutlierWarningNote (warn border and fill, Phosphor Warning icon) with its own sentence; purely informational:
 * it never changes a number, score or verdict. The evidence line is the gate's own description of what moved. */
export function PartialBalanceSheetNote({ flags }: Props) {
  const flag = partialBalanceSheetFlag(flags);
  if (!flag) return null;
  return (
    <div className="space-y-1 rounded-md border border-warn/40 bg-warn/10 p-3">
      <p className="text-sm text-warn">
        <Warning size={16} weight="bold" aria-hidden="true" className="-mt-0.5 mr-1.5 inline" />
        <span className="sr-only">Warning: </span>
        {partialBalanceSheetMessage(flag)}
      </p>
      {flag.evidence && <p className="text-xs text-warn/80">{flag.evidence}</p>}
    </div>
  );
}

/** Muted line for a quarter that has been reported but is not in the cached statements yet. */
export function NotLandedLine({ flags }: Props) {
  const flag = notLandedFlag(flags);
  if (!flag) return null;
  return <p className="text-xs text-text-tertiary">{notLandedMessage(flag)}</p>;
}

/** The Ratios tab and the Step 4 ROIC/ROE display: figures FMP computes, which this app never rescales. Shown when the
 * balance-sheet gate fired or a placeholder or scale break sits on a newest-period row; never for "not landed" alone. */
export function FmpRatiosNote({ flags }: Props) {
  if (!showsFmpRatiosNote(flags)) return null;
  return <p className="text-xs text-warn">{RATIOS_FROM_FMP_MESSAGE}</p>;
}
