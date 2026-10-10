import { cn } from "@/lib/utils";
import { gaugeGeometry, type GaugeDirection } from "@/lib/chartGeometry";

interface Props {
  /** The ratio. null draws an empty track and "No data". */
  value: number | null;
  /** The line the ratio passes at. */
  passLine: number;
  /** The hard limit beyond it. Equal to `passLine` (or omitted) for a ratio with one line only: one tick, no monitor zone. */
  hardLimit?: number;
  /** "ceiling": lower is safer (Debt/EBITDA, servicing, gearing, NPL). "floor": higher is safer (current ratio, CET1). */
  direction: GaugeDirection;
  /** Formats the value and the lines, e.g. `(n) => `${n.toFixed(1)}x``. */
  format: (n: number) => string;
  /** Replaces the whole visual with the reason (Insurance has no debt ratios, an excluded ratio). */
  notApplicable?: string;
  /** Names the ratio for assistive tech. */
  label?: string;
  /** false hides the caption under the track. */
  caption?: boolean;
  className?: string;
}

/** A ratio on a track with its pass line and hard limit. Neutral fill; amber only once the value is past the pass line, with the monitor
 * zone between the two lines tinted. No tooltip: the caption writes the lines out. docs/design-system-charts.md, "Dashboard primitives". */
export function ThresholdGauge({ value, passLine, hardLimit, direction, format, notApplicable, label = "Ratio", caption = true, className }: Props) {
  if (notApplicable) {
    return <p className={cn("text-xs text-text-tertiary", className)}>{notApplicable}</p>;
  }

  const limit = hardLimit ?? passLine;
  const g = gaugeGeometry(value, passLine, limit, direction);
  const hasZone = g.zone !== null;
  const passWord = direction === "ceiling" ? "or lower" : "or higher";
  const captionText = `Passes at ${format(passLine)} ${passWord}${hasZone ? ` · hard limit ${format(limit)}` : ""}`;
  const valueText = value === null ? "No data" : `${format(value)}${g.overflow ? " ›" : ""}`;
  const stateText = g.state === "ok" ? "within the pass line" : g.state === "monitor" ? "past the pass line, inside the hard limit" : g.state === "breach" ? "past the hard limit" : "no data";

  return (
    <div
      role="img"
      aria-label={`${label}: ${valueText}. ${captionText}. ${stateText}.`}
      data-state={g.state ?? "missing"}
      className={cn("flex flex-col gap-1.5", className)}
    >
      <div className="flex items-center gap-3">
        <div className="relative h-2 min-w-0 flex-1 rounded-full bg-surface-2">
          {g.zone && <div className="absolute inset-y-0 bg-warn/20" style={{ left: `${g.zone.leftPct}%`, width: `${g.zone.widthPct}%` }} />}
          {g.fillPct !== null && (
            <div
              data-testid="gauge-fill"
              className={cn("absolute inset-y-0 left-0 rounded-full", g.state === "ok" ? "bg-text-tertiary" : "bg-warn")}
              style={{ width: `${g.fillPct}%` }}
            />
          )}
          {[g.passPct, ...(hasZone ? [g.limitPct] : [])].map((pct, i) => (
            <div key={i} data-testid="gauge-tick" className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-full bg-text-primary" style={{ left: `${pct}%` }} />
          ))}
        </div>
        <span className={cn("w-20 shrink-0 text-right font-mono text-xs tabular-nums", value === null ? "text-text-tertiary" : "text-text-primary")}>
          {valueText}
        </span>
      </div>
      {caption && <p className="text-xs text-text-tertiary">{captionText}</p>}
    </div>
  );
}
