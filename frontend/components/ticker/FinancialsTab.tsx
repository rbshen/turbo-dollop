"use client";

import { useState } from "react";

import { NotLandedLine } from "@/components/shared/DataQualityNote";
import { DataQualityFlagsNote } from "@/components/ticker/DataQualityFlagsNote";
import { FinancialsStatementTable } from "@/components/ticker/FinancialsStatementTable";
import { HistoricalTrendsGrid } from "@/components/ticker/HistoricalTrendsGrid";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Tabs } from "@/components/ui/tabs";
import type { FinancialsStatementOut } from "@/lib/api/types";
import type { StatementKind } from "@/lib/dataQuality";
import { useFinancials } from "@/lib/hooks/useFinancials";

type StatementKey = "income" | "balanceSheet" | "cashFlow";
type Period = "annual" | "quarterly";

const STATEMENT_TABS: { key: StatementKey; label: string }[] = [
  { key: "income", label: "Income Statement" },
  { key: "balanceSheet", label: "Balance Sheet" },
  { key: "cashFlow", label: "Cash Flow" },
];

const STATEMENT_KIND: Record<StatementKey, StatementKind> = {
  income: "income",
  balanceSheet: "balance_sheet",
  cashFlow: "cash_flow",
};

const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "annual", label: "Annual" },
  { value: "quarterly", label: "Quarterly" },
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
      <DataQualityFlagsNote ticker={ticker} />

      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-text-secondary">Historical Trends</h2>
        <HistoricalTrendsGrid ticker={ticker} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          aria-label="Financial statement"
          value={statement}
          onValueChange={(next) => setStatement(next as StatementKey)}
          items={STATEMENT_TABS.map(({ key, label }) => ({ value: key, label }))}
        />

        <SegmentedControl
          aria-label="Statement period"
          value={period}
          onValueChange={(next) => setPeriod(next as Period)}
          options={PERIOD_OPTIONS}
        />
      </div>

      <p className="text-xs text-text-tertiary">
        All numbers are in {data.reported_currency ?? "USD"} millions, except per-share data, ratios, and percentages.
        {data.reported_currency && data.reported_currency !== "USD" && (
          <> Figures are as reported by {ticker}, not converted (unlike the Valuation tab, which converts to {ticker}&apos;s quote currency).</>
        )}
      </p>

      <NotLandedLine flags={data.data_quality} />

      <FinancialsStatementTable
        ticker={ticker}
        periodType={period}
        data={statementData[period]}
        reportedCurrency={data.reported_currency ?? "USD"}
        statement={STATEMENT_KIND[statement]}
        dataQuality={data.data_quality}
      />
    </div>
  );
}
