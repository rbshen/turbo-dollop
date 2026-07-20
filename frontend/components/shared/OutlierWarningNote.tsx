import type { OutlierWarning } from "@/lib/api/types";
import { fmtCompactMoney } from "@/lib/format";

interface Props {
  warnings: OutlierWarning[];
  labels: Record<string, string>;
}

/** Purely informational note for a TTM-summed flow metric where one of the
 * 4 summed quarters looked anomalous against its trailing history (see
 * backend/ttm.py::sum_last_four_quarters) -- never changes the number,
 * score, or verdict it's attached to. Shared by Step5Card and the ticker
 * header's metrics grid, the two current consumers of outlier_warnings. */
export function OutlierWarningNote({ warnings, labels }: Props) {
  if (warnings.length === 0) return null;

  return (
    <div className="space-y-1 rounded-md border border-amber-800/40 bg-amber-900/10 p-3">
      <p className="text-sm text-amber-300">
        ⚠️ One or more recent quarters look anomalous compared to trailing history — verify independently before
        relying on these numbers.
      </p>
      <ul className="space-y-1.5 text-xs text-amber-200/80">
        {warnings.map((w, i) => (
          <li key={i}>
            <div>
              {labels[w.metric] ?? w.metric}
              {w.date ? ` (${w.date})` : ""}: FMP {fmtCompactMoney(w.value)} vs. trailing median{" "}
              {fmtCompactMoney(w.trailing_median)}
            </div>
            {w.sec_cross_check &&
              (w.sec_cross_check.available ? (
                <div className={w.sec_cross_check.matches_fmp ? "text-emerald-300/90" : "text-red-300"}>
                  SEC EDGAR (filed value): {fmtCompactMoney(w.sec_cross_check.sec_value!)} — {w.sec_cross_check.note}
                </div>
              ) : (
                <div className="text-zinc-500">{w.sec_cross_check.note}</div>
              ))}
          </li>
        ))}
      </ul>
    </div>
  );
}
