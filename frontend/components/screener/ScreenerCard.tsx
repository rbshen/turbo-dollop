import Link from "next/link";

import { ScoreBadge } from "@/components/step1/ScoreBadge";
import type { TickerScoreOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtNumber } from "@/lib/format";

interface Props {
  data: TickerScoreOut;
}

const STEP_CHIPS: { key: keyof TickerScoreOut; verdictKey: keyof TickerScoreOut; label: string }[] = [
  { key: "step1_score", verdictKey: "step1_verdict", label: "S1" },
  { key: "step2_score", verdictKey: "step2_verdict", label: "S2" },
  { key: "step4_score", verdictKey: "step4_verdict", label: "S4" },
  { key: "step5_score", verdictKey: "step5_verdict", label: "S5" },
];

function chipClass(score: number | null, verdict: string | null): string {
  if (score == null) return "border-zinc-800 bg-zinc-900 text-zinc-600"; // exempt/unavailable for this step
  if (verdict === "Fail") return "border-red-800/40 bg-red-900/20 text-red-400";
  // Step 5's "Pass with caution" (a Borderline breach excused by its
  // tiebreaker) -- distinct from both a clean Pass and a Fail.
  if (verdict === "Pass with caution") return "border-amber-700/50 bg-amber-900/20 text-amber-400";
  if (score > 90) return "border-emerald-700/40 bg-emerald-900/20 text-emerald-300";
  return "border-zinc-700 bg-zinc-800/60 text-zinc-300";
}

export function ScreenerCard({ data }: Props) {
  return (
    <Link
      href={`/tickers/${data.ticker}`}
      className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 transition-colors hover:border-zinc-600"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
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

      <div className="flex flex-wrap gap-1.5">
        {STEP_CHIPS.map(({ key, verdictKey, label }) => {
          const score = data[key] as number | null;
          const verdict = data[verdictKey] as string | null;
          return (
            <span key={label} className={`rounded-full border px-2 py-0.5 text-xs font-medium ${chipClass(score, verdict)}`}>
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
  );
}
