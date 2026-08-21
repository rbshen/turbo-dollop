import { cn } from "@/lib/utils";

// Low to high -- left to right, bottom-aligned (grows from one baseline), a
// scaled-down version of this app's usual bar-chart mark conventions
// (rounded top, small gap between bars) sized for a table-cell icon. A
// 5-entry ladder so both the existing 3-bar callers (Moat/Value/vs-SPY,
// maxBars=3 default) and the 5-bar TREND column can share one component --
// slice(-maxBars) keeps the tallest `maxBars` steps, so a 3-bar caller's
// visual proportions are unchanged from before this was generalized.
const BAR_HEIGHTS = ["h-1", "h-1.5", "h-2.5", "h-3", "h-3.5"];

interface Props {
  /** How many bars (left to right) render filled/colored; the rest render as
   * a muted unfilled placeholder. Generic over any N-state metric (Moat/
   * Value/vs-SPY at maxBars=3; TREND at maxBars=5). */
  level: number;
  /** Tailwind bg-* class for the filled bars, e.g. "bg-positive-strong". */
  color: string;
  /** Total bar count. Defaults to 3, matching every caller before TREND. */
  maxBars?: number;
}

export function SignalBars({ level, color, maxBars = 3 }: Props) {
  const heights = BAR_HEIGHTS.slice(-maxBars);
  return (
    <div className="flex items-end justify-center gap-0.5">
      {heights.map((heightClass, i) => (
        <div key={i} className={cn("w-1 rounded-t-sm", heightClass, i < level ? color : "bg-border-subtle")} />
      ))}
    </div>
  );
}
