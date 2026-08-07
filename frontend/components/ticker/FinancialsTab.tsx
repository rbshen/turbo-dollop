"use client";

import { useState } from "react";

import { SegmentedControl } from "@/components/shared/SegmentedControl";
import { FinancialsStatementTable } from "@/components/ticker/FinancialsStatementTable";
import { HistoricalTrendsGrid } from "@/components/ticker/HistoricalTrendsGrid";
import type { FinancialsStatementOut } from "@/lib/api/types";
import { useFinancials } from "@/lib/hooks/useFinancials";

type StatementKey = "income" | "balanceSheet" | "cashFlow";
type Period = "annual" | "quarterly";

const STATEMENT_TABS: { key: StatementKey; label: string }[] = [
  { key: "income", label: "Income Statement" },
  { key: "balanceSheet", label: "Balance Sheet" },
  { key: "cashFlow", label: "Cash Flow" },
];

const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "annual", label: "annual" },
  { value: "quarterly", label: "quarterly" },
];

interface Props {
  ticker: string;
}

export function FinancialsTab({ ticker }: Props) {
  const { data, error } = useFinancials(ticker);
  const [statement, setStatement] = useState<StatementKey>("income");
  const [period, setPeriod] = useState<Period>("annual");

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-negative">
          Couldn&apos;t load {ticker} — {error.message}
        </span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-text-tertiary animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  const statementData: FinancialsStatementOut =
    statement === "income" ? data.income_statement : statement === "balanceSheet" ? data.balance_sheet : data.cash_flow;

  return (
    <div className="space-y-6 py-6">
      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-text-secondary">Historical Trends</h2>
        <HistoricalTrendsGrid ticker={ticker} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 overflow-x-auto border-b border-border-card">
          {STATEMENT_TABS.map(({ key, label }) => {
            const isActive = key === statement;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setStatement(key)}
                className={`shrink-0 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive ? "border-brand text-brand" : "border-transparent text-text-secondary hover:text-text-primary"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>

        <SegmentedControl value={period} onChange={setPeriod} options={PERIOD_OPTIONS} />
      </div>

      <p className="text-xs text-text-tertiary">
        All numbers are in {data.reported_currency ?? "USD"} millions, except per-share data, ratios, and percentages.
        {data.reported_currency && data.reported_currency !== "USD" && (
          <> Figures are as reported by {ticker}, not converted to USD (unlike the Valuation tab).</>
        )}
      </p>

      <FinancialsStatementTable data={statementData[period]} />
    </div>
  );
}
