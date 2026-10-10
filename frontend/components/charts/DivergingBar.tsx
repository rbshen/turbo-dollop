import { cn } from "@/lib/utils";
import { divergingGeometry, type DivergingTone } from "@/lib/chartGeometry";

interface Props {
  /** The signed gap in percentage points. null draws the axis alone with "No data". */
  value: number | null;
  /** Half-width of the "in line" band, same unit as `value`. */
  band: number;
  /** Half-scale: the axis runs -scale to +scale. Share one across a stack of bars (`divergingScale`). */
  scale: number;
  /** Formats the value; the default is a signed one-decimal percentage. */
  format?: (n: number) => string;
  /** The stock's own return and the benchmark's, written next to the gap so it cannot be read as a return. */
  stockReturn?: number | null;
  benchmarkReturn?: number | null;
  benchmarkLabel?: string;
  label?: string;
  className?: string;
}

const defaultFormat = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)}%`;

const BAR_CLASS: Record<DivergingTone, string> = {
  ahead: "bg-positive",
  behind: "bg-negative",
  in_line: "bg-text-tertiary",
};
const WORD: Record<DivergingTone, string> = { ahead: "ahead", behind: "behind", in_line: "in line" };

/** A signed gap around a centre axis with the in-line band shaded. Green ahead, red behind, neutral inside the band: the one place besides
 * the stage timeline that uses green and red, and it says ahead or behind a benchmark, never pass or fail. docs/design-system-charts.md. */
export function DivergingBar({ value, band, scale, format = defaultFormat, stockReturn, benchmarkReturn, benchmarkLabel = "benchmark", label = "Gap", className }: Props) {
  const g = divergingGeometry(value, band, scale);
  const valueText = value === null ? "No data" : `${format(value)}${g.overflow ? " ›" : ""}`;
  const returns =
    stockReturn != null && benchmarkReturn != null ? `stock ${format(stockReturn)} · ${benchmarkLabel} ${format(benchmarkReturn)}` : null;

  return (
    <div
      role="img"
      aria-label={`${label}: ${valueText}${g.tone ? `, ${WORD[g.tone]}` : ""}${returns ? `. ${returns}` : ""}`}
      data-tone={g.tone ?? "missing"}
      className={cn("flex flex-col gap-1", className)}
    >
      <div className="flex items-center gap-3">
        <div className="relative h-4 min-w-0 flex-1">
          <div className="absolute inset-x-0 top-1/2 h-px bg-border-subtle" />
          <div data-testid="diverging-band" className="absolute inset-y-0 rounded-sm bg-surface-2" style={{ left: `${g.bandLeftPct}%`, width: `${g.bandWidthPct}%` }} />
          {g.tone && (
            <div
              data-testid="diverging-bar"
              className={cn("absolute inset-y-1 rounded-sm", BAR_CLASS[g.tone])}
              style={{ left: `${g.barFromPct}%`, width: `${g.barWidthPct}%` }}
            />
          )}
          <div className="absolute inset-y-0 left-1/2 w-px bg-border-card" />
        </div>
        <span className={cn("w-24 shrink-0 text-right font-mono text-xs tabular-nums", value === null ? "text-text-tertiary" : "text-text-primary")}>
          {valueText}
          {g.tone && <span className="ml-1.5 font-sans text-text-tertiary">{WORD[g.tone]}</span>}
        </span>
      </div>
      {returns && <p className="text-xs text-text-tertiary">{returns}</p>}
    </div>
  );
}
