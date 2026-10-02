import Link from "next/link";

import { WeinsteinStagePill } from "@/components/ticker/WeinsteinStagePill";
import { Badge } from "@/components/ui/badge";
import type { EtfScreenerRowOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtMoney, fmtNumber, fmtPct, fmtPlainPct, pnlClass } from "@/lib/format";
import { pillLabel } from "@/lib/tierColor";
import { cn } from "@/lib/utils";

interface Props {
  data: EtfScreenerRowOut;
}

/** "+3.4 pp": a percentage-point difference (1Y vs SPY), signed like fmtPct. */
function fmtPoints(n: number): string {
  if (Math.abs(n) < 0.05) return "0.0 pp";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)} pp`;
}

function Metric({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-text-tertiary">{label}</p>
      <p className={cn("break-words font-mono text-text-secondary", className)}>{children}</p>
    </div>
  );
}

// The ETFs page's twin of ScreenerCard: same box, same tokens, same whole-card Link that opens the ticker page in a new
// tab (see ScreenerCard for why the tokens sit on the Link rather than on a Card). The body differs because an ETF has
// no score, sector or company type: asset class and the Weinstein pill replace them, and the footer is fund facts and
// price-relative figures. A value the row does not have reads "—"; Beta is already null for a non-equity fund.
export function EtfScreenerCard({ data }: Props) {
  return (
    <Link
      href={`/tickers/${data.ticker}`}
      target="_blank"
      rel="noopener noreferrer"
      className="flex flex-col gap-3 rounded-lg border border-border-card bg-surface p-4 transition-colors hover:border-brand"
    >
      <div className="min-w-0">
        <p className="truncate font-mono text-sm font-bold text-text-primary">{data.ticker}</p>
        <p className="truncate text-xs text-text-tertiary">{data.name ?? "—"}</p>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone="neutral">{data.asset_class ? pillLabel(data.asset_class) : "Unclassified"}</Badge>
        <WeinsteinStagePill data={data} />
      </div>

      <div className="mt-auto grid grid-cols-3 gap-x-2 gap-y-3 border-t border-border-subtle pt-2 text-xs">
        <Metric label="Quote">{data.last_price != null ? fmtMoney(data.last_price) : "—"}</Metric>
        <Metric label="1D" className={data.pct_change_1d != null ? pnlClass(data.pct_change_1d) : undefined}>
          {data.pct_change_1d != null ? fmtPct(data.pct_change_1d) : "—"}
        </Metric>
        <Metric label="AUM">{data.aum != null ? fmtCompactMoney(data.aum) : "—"}</Metric>
        <Metric label="Exp. ratio">{data.expense_ratio != null ? fmtPlainPct(data.expense_ratio, 2) : "—"}</Metric>
        <Metric label="1Y vs SPY" className={data.vs_spy_1y != null ? pnlClass(data.vs_spy_1y) : undefined}>
          {data.vs_spy_1y != null ? fmtPoints(data.vs_spy_1y) : "—"}
        </Metric>
        <Metric label="Beta">{data.beta != null ? fmtNumber(data.beta) : "—"}</Metric>
      </div>
    </Link>
  );
}
