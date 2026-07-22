import { Fragment } from "react";

import type { FinancialsPeriodOut } from "@/lib/api/types";
import { fmtNumber, fmtTableNumber } from "@/lib/format";

interface Props {
  data: FinancialsPeriodOut;
}

function formatValue(value: number | null, unit: string): string {
  if (value == null) return "—";
  // "money" and "shares" both scale to millions with no suffix -- the
  // "figures in USD millions" note under the sub-tabs covers the scale
  // once instead of repeating a per-cell unit; "shares" rows spell out
  // "(millions)" in their own label since they aren't actually USD.
  return unit === "per_share" ? fmtNumber(value) : fmtTableNumber(value);
}

// Same sticky-label-column + scrollable-value-table layout as Step 1's
// FinancialsSection, generalized to render optional group subheaders
// (Balance Sheet/Cash Flow) -- Income Statement's single ungrouped list
// just never has a group.label, so no subheader row is rendered for it.
export function FinancialsStatementTable({ data }: Props) {
  return (
    <div className="flex">
      <table className="shrink-0 border-separate border-spacing-0 text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
            <th className="whitespace-nowrap border-b border-zinc-800 py-2 pr-8 font-medium">Line item</th>
          </tr>
        </thead>
        <tbody>
          {data.groups.map((group, gi) => (
            <Fragment key={gi}>
              {group.label && (
                <tr>
                  <td className="whitespace-nowrap border-b border-zinc-900 pt-4 pb-1 pr-8 text-xs font-semibold uppercase tracking-widest text-zinc-500">
                    {group.label}
                  </td>
                </tr>
              )}
              {group.items.map((item) => (
                <tr key={item.label}>
                  <td
                    className={`whitespace-nowrap border-b border-zinc-900 py-2 pr-8 ${
                      item.emphasis ? "font-medium text-zinc-100" : "text-zinc-400"
                    }`}
                  >
                    {item.label}
                  </td>
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>

      <div className="flex-1 overflow-x-auto">
        <table className="w-full min-w-max border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
              {data.periods.map((period, i) => (
                <th key={i} className="whitespace-nowrap border-b border-zinc-800 py-2 pr-4 text-right font-medium">
                  {period}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.groups.map((group, gi) => (
              <Fragment key={gi}>
                {group.label && (
                  <tr>
                    {data.periods.map((_, i) => (
                      <td key={i} className="border-b border-zinc-900 pt-4 pb-1" />
                    ))}
                  </tr>
                )}
                {group.items.map((item) => (
                  <tr key={item.label}>
                    {item.values.map((value, i) => (
                      <td
                        key={i}
                        className={`border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums ${
                          item.emphasis ? "font-medium text-zinc-100" : "text-zinc-300"
                        }`}
                      >
                        {formatValue(value, item.unit)}
                      </td>
                    ))}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
