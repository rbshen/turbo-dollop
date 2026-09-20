import type { InsiderNotableTrade } from "@/lib/api/types";
import { fmtInsiderRole, fmtInsiderValue, fmtIsoDate } from "@/lib/insiderActivity";
import { fmtCompactNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

interface CardProps {
  title: string;
  trade: InsiderNotableTrade | null;
  tone: "positive" | "negative";
}

function NotableTradeCard({ title, trade, tone }: CardProps) {
  const role = trade ? fmtInsiderRole(trade.insider_role) : null;
  return (
    <div className="space-y-1.5 rounded-lg border border-border-card bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-widest text-text-tertiary">{title}</p>
      {trade ? (
        <>
          <p className={cn("font-mono text-lg font-semibold tabular-nums", tone === "positive" ? "text-positive" : "text-negative")}>
            {fmtInsiderValue(trade)}
          </p>
          <p className="text-sm text-text-primary">
            {trade.insider_name}
            {role && <span className="text-text-tertiary"> · {role}</span>}
          </p>
          <p className="text-xs text-text-tertiary">
            {fmtCompactNumber(trade.shares)} shares · {fmtIsoDate(trade.transaction_date)}
            {trade.fill_count > 1 && ` · ${trade.fill_count} fills`}
          </p>
        </>
      ) : (
        <p className="text-sm text-text-tertiary">None in the fetched filings.</p>
      )}
    </div>
  );
}

interface Props {
  buy: InsiderNotableTrade | null;
  sale: InsiderNotableTrade | null;
}

export function InsiderNotableTrades({ buy, sale }: Props) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <NotableTradeCard title="Largest open-market buy" trade={buy} tone="positive" />
      <NotableTradeCard title="Largest open-market sale" trade={sale} tone="negative" />
    </div>
  );
}
