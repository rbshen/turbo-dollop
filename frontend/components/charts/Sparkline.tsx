import { cn } from "@/lib/utils";
import { SERIES_COLORS } from "@/lib/chartSeries";
import { sparklineGeometry } from "@/lib/chartGeometry";

interface Props {
  values: Array<number | null | undefined>;
  /** Captions under the first and the last point (dates). */
  startLabel?: string;
  endLabel?: string;
  /** Formats the last value, written at the right of the end captions. */
  format?: (n: number) => string;
  height?: number;
  /** Shown instead of the line under two points. */
  emptyText?: string;
  label?: string;
  className?: string;
}

/** A plain line: no axes, no fill, no hover. The one-series colour (series-1) like every single-series chart. */
export function Sparkline({ values, startLabel, endLabel, format, height = 40, emptyText = "No price history", label = "Trend", className }: Props) {
  const g = sparklineGeometry(values);
  if (g.points === null) return <p className={cn("text-xs text-text-tertiary", className)}>{emptyText}</p>;

  const last = [...values].reverse().find((v): v is number => typeof v === "number" && Number.isFinite(v));
  return (
    <div role="img" aria-label={`${label}${startLabel && endLabel ? ` from ${startLabel} to ${endLabel}` : ""}${format && last !== undefined ? `, last ${format(last)}` : ""}`} className={cn("flex flex-col gap-1", className)}>
      <div className="relative" style={{ height }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible" aria-hidden>
          <polyline points={g.points} fill="none" stroke={SERIES_COLORS[0]} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {g.last && (
          <span
            data-testid="sparkline-end"
            className="absolute size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-series-1"
            style={{ left: `${g.last.xPct}%`, top: `${g.last.yPct}%` }}
          />
        )}
      </div>
      {(startLabel || endLabel || (format && last !== undefined)) && (
        <div className="flex items-baseline justify-between gap-2 text-xs text-text-tertiary">
          <span>{startLabel}</span>
          <span>
            {endLabel}
            {format && last !== undefined && <span className="ml-1.5 font-mono tabular-nums text-text-secondary">{format(last)}</span>}
          </span>
        </div>
      )}
    </div>
  );
}
