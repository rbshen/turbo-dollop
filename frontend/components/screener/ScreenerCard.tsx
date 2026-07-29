import { Check } from "@phosphor-icons/react";
import Link from "next/link";

import { MoatPill } from "@/components/ticker/MoatPill";
import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { ValuationBadge } from "@/components/screener/ValuationBadge";
import type { TickerScoreOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtNumber } from "@/lib/format";
import { chipClassFor } from "@/lib/tierColor";

interface Props {
  data: TickerScoreOut;
  selected: boolean;
  onToggle: (ticker: string) => void;
  // True once the bulk-select cap is reached and this card isn't already
  // one of the selected ones -- disables (not hides) its own checkbox.
  selectionDisabled: boolean;
}

const STEP_CHIPS: { key: keyof TickerScoreOut; verdictKey: keyof TickerScoreOut; label: string }[] = [
  { key: "step1_score", verdictKey: "step1_verdict", label: "F" },
  { key: "step2_score", verdictKey: "step2_verdict", label: "G" },
  { key: "step5_score", verdictKey: "step5_verdict", label: "D" },
  { key: "step4_score", verdictKey: "step4_verdict", label: "P" },
];

export function ScreenerCard({ data, selected, onToggle, selectionDisabled }: Props) {
  const checkboxDisabled = selectionDisabled && !selected;

  function handleToggle(e: React.MouseEvent) {
    // The checkbox is a sibling of the Link, not nested inside it (invalid
    // HTML + click-through fighting) -- but its own click must still never
    // fall through to the Link underneath it.
    e.preventDefault();
    e.stopPropagation();
    if (checkboxDisabled) return;
    onToggle(data.ticker);
  }

  return (
    <div className="relative">
      <button
        type="button"
        onMouseDown={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onClick={handleToggle}
        disabled={checkboxDisabled}
        aria-label={selected ? `Deselect ${data.ticker}` : `Select ${data.ticker}`}
        className={`absolute left-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded border transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
          selected ? "border-blue-500 bg-blue-500 text-white" : "border-zinc-600 bg-zinc-900 hover:border-zinc-400"
        }`}
      >
        {selected && <Check size={12} weight="bold" />}
      </button>

      <Link
        href={`/tickers/${data.ticker}`}
        target="_blank"
        rel="noopener noreferrer"
        className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 transition-colors hover:border-zinc-600"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 pl-6">
            <p className="truncate font-mono text-sm font-bold text-zinc-100">{data.ticker}</p>
            <p className="truncate text-xs text-zinc-500">{data.company_name ?? "—"}</p>
          </div>
          {data.overall_score != null && data.overall_verdict != null ? (
            <ScoreBadge score={data.overall_score} verdict={data.overall_verdict} />
          ) : (
            <span className="inline-flex shrink-0 items-center rounded-lg border border-zinc-700 bg-zinc-800/60 px-4 py-2 text-xs font-medium text-zinc-500">
              Incomplete
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="rounded-md border border-zinc-700/40 bg-zinc-800 px-1.5 py-0.5 font-semibold text-zinc-400">
            {data.company_type ?? "Unclassified"}
          </span>
          <span className="truncate text-zinc-600">{data.sector ?? "—"}</span>
        </div>

        {(data.moat != null || data.valuation_verdict != null) && (
          <div className="flex flex-wrap items-center gap-1.5">
            <MoatPill moat={data.moat} />
            <ValuationBadge verdict={data.valuation_verdict} />
          </div>
        )}

        <div className="flex flex-wrap gap-1.5">
          {STEP_CHIPS.map(({ key, verdictKey, label }) => {
            const score = data[key] as number | null;
            const verdict = data[verdictKey] as string | null;
            return (
              <span key={label} className={`rounded-full border px-2 py-0.5 text-xs font-medium ${chipClassFor(score, verdict)}`}>
                {label} · {score ?? "—"}
              </span>
            );
          })}
        </div>

        <div className="mt-auto grid grid-cols-3 gap-2 border-t border-zinc-800 pt-2 text-xs">
          <div>
            <p className="text-zinc-600">Mkt Cap</p>
            <p className="font-mono text-zinc-300">{data.market_cap != null ? fmtCompactMoney(data.market_cap) : "—"}</p>
          </div>
          <div>
            <p className="text-zinc-600">P/E</p>
            <p className="font-mono text-zinc-300">{data.pe_ratio != null ? fmtNumber(data.pe_ratio) : "—"}</p>
          </div>
          <div>
            <p className="text-zinc-600">Beta</p>
            <p className="font-mono text-zinc-300">{data.beta != null ? fmtNumber(data.beta) : "—"}</p>
          </div>
        </div>
      </Link>
    </div>
  );
}
