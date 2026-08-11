import { cn } from "@/lib/utils";

// Low, mid, high -- left to right, bottom-aligned (grows from one baseline),
// a scaled-down version of this app's usual bar-chart mark conventions
// (rounded top, small gap between bars) sized for a table-cell icon.
const BAR_HEIGHTS = ["h-1.5", "h-2.5", "h-3.5"];

interface Props {
  /** How many bars (left to right) render filled/colored; the rest render as
   * a muted unfilled placeholder. 1 = low only, 3 = all three. Generic over
   * any 3-state metric (Moat today; Valuation/vs-SPY could reuse this later
   * with their own level/color mapping). */
  level: 1 | 2 | 3;
  /** Tailwind bg-* class for the filled bars, e.g. "bg-positive-strong". */
  color: string;
}

export function SignalBars({ level, color }: Props) {
  return (
    <div className="flex items-end justify-center gap-0.5">
      {BAR_HEIGHTS.map((heightClass, i) => (
        <div key={i} className={cn("w-1 rounded-t-sm", heightClass, i < level ? color : "bg-border-subtle")} />
      ))}
    </div>
  );
}
