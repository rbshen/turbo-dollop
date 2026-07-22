import { cn } from "@/lib/utils";

const VERDICT_STYLES: Record<string, string> = {
  undervalued: "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  overvalued: "bg-red-900/40 text-red-400 border-red-800/40",
  fair: "bg-zinc-800 text-zinc-400 border-zinc-700/40",
};

const VERDICT_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fair value",
};

interface Props {
  verdict: string | null;
  price: number | null;
  /** e.g. "DCF" / "P/B" / "PSG" -- the Step 3 method the price was derived
   * from, shown alongside the verdict so it never reads as a bare,
   * unexplained "Undervalued". */
  method?: string | null;
}

export function FairValuePill({ verdict, price, method }: Props) {
  if (!verdict || price == null) return null;
  const cls = VERDICT_STYLES[verdict] ?? VERDICT_STYLES.fair;
  const label = VERDICT_LABELS[verdict] ?? verdict;

  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold", cls)}>
      {label}
      <span className="font-mono tabular-nums">${price.toFixed(2)}</span>
      {method && <span className="font-normal opacity-70">({method})</span>}
    </span>
  );
}
