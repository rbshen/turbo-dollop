"use client";

import { MagnifyingGlass } from "@phosphor-icons/react";
import { useState } from "react";

import { apiFetch } from "@/lib/api/client";
import { fmtCompactMoney } from "@/lib/format";
import type { SecCrossCheck } from "@/lib/api/types";

// Phase 3a (2026-08-16): on-demand SEC EDGAR cross-check, scoped to exactly
// the two Cash Flow fields FinancialsStatementTable.tsx's own
// INCOMPLETE_COVERAGE_LABELS already flags as having a real FMP data gap
// (Income Taxes Paid, Interest Paid) -- not a generic "any cell" lookup,
// see the backend's own SEC_CELL_CHECK_FIELDS docstring for why that
// doesn't generalize. Single ticker + single field + single period per
// click -- there is no batch/bulk trigger anywhere in this component.
export type SecCellCheckField = "incomeTaxesPaid" | "interestPaid";

interface Props {
  ticker: string;
  field: SecCellCheckField;
  periodEnd: string;
}

type Status = "idle" | "loading" | "done" | "error";

export function SecCellCheckButton({ ticker, field, periodEnd }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<SecCrossCheck | null>(null);

  async function handleClick() {
    setStatus("loading");
    try {
      const data = await apiFetch<SecCrossCheck>(
        `/tickers/${ticker}/financials/cash-flow-cell-check?field=${field}&period_end=${periodEnd}`
      );
      setResult(data);
      setStatus("done");
    } catch {
      setStatus("error");
    }
  }

  if (status === "idle") {
    return (
      <button
        type="button"
        onClick={handleClick}
        title="Check SEC EDGAR's filed figure for this period"
        className="ml-1.5 inline-flex align-middle text-text-tertiary transition-colors hover:text-brand"
      >
        <MagnifyingGlass size={12} weight="bold" />
      </button>
    );
  }

  if (status === "loading") {
    return <span className="ml-1.5 text-[10px] text-text-tertiary">checking…</span>;
  }

  if (status === "error") {
    return (
      <span className="ml-1.5 text-[10px] text-negative" title="SEC EDGAR lookup failed -- try again">
        error
      </span>
    );
  }

  // status === "done"
  if (!result || !result.available) {
    return (
      <span className="ml-1.5 text-[10px] text-text-tertiary" title={result?.note}>
        n/a
      </span>
    );
  }

  return (
    <span
      className={`ml-1.5 text-[10px] font-semibold ${result.matches_fmp ? "text-positive" : "text-negative"}`}
      title={result.note}
    >
      SEC: {fmtCompactMoney(result.sec_value ?? 0)}
    </span>
  );
}
