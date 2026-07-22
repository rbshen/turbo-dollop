"use client";

import { useState } from "react";

import { FinancialsStatementTable } from "@/components/ticker/FinancialsStatementTable";
import type { FinancialsStatementOut } from "@/lib/api/types";
import { useFinancials } from "@/lib/hooks/useFinancials";

type StatementKey = "income" | "balanceSheet" | "cashFlow";
type Period = "annual" | "quarterly";

const STATEMENT_TABS: { key: StatementKey; label: string }[] = [
  { key: "income", label: "Income Statement" },
  { key: "balanceSheet", label: "Balance Sheet" },
  { key: "cashFlow", label: "Cash Flow" },
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
        <span className="text-sm text-red-400">
          Couldn&apos;t load {ticker} — {error.message}
        </span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-zinc-600 animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  const statementData: FinancialsStatementOut =
    statement === "income" ? data.income_statement : statement === "balanceSheet" ? data.balance_sheet : data.cash_flow;

  return (
    <div className="space-y-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 overflow-x-auto border-b border-zinc-800">
          {STATEMENT_TABS.map(({ key, label }) => {
            const isActive = key === statement;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setStatement(key)}
                className={`shrink-0 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive ? "border-zinc-100 text-zinc-100" : "border-transparent text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>

        <div className="inline-flex overflow-hidden rounded-md border border-zinc-700 text-xs">
          {(["annual", "quarterly"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={`px-2.5 py-1 capitalize transition-colors ${
                period === p ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs text-zinc-500">All numbers are in USD millions, except per-share data, ratios, and percentages.</p>

      <FinancialsStatementTable data={statementData[period]} />
    </div>
  );
}
