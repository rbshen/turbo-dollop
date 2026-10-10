import { cn } from "@/lib/utils";
import { tierScaleGeometry } from "@/lib/chartGeometry";

interface Props {
  /** The value, or null for "No data". A negative value fills nothing; the label still shows it. */
  value: number | null;
  /** The scale runs 0 to `max`. */
  max: number;
  /** The tier lines, ascending, drawn as labelled ticks. */
  bands: number[];
  format: (n: number) => string;
  label?: string;
  /** A line under the scale, e.g. the analyst count. */
  caption?: string;
  className?: string;
}

/** A plain scale with tier lines and no verdict colour: the growth rate against the 5, 10 and 15% bands. Neutral fill; the pill beside it carries the verdict. */
export function TierScale({ value, max, bands, format, label = "Value", caption, className }: Props) {
  const g = tierScaleGeometry(value, max, bands);
  const valueText = value === null ? "No data" : `${format(value)}${g.overflow ? " ›" : ""}`;
  return (
    <div role="img" aria-label={`${label}: ${valueText}. Lines at ${bands.map(format).join(", ")}.`} className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-center gap-3">
        <div className="relative h-2 min-w-0 flex-1 rounded-full bg-surface-2">
          {g.fillPct !== null && <div data-testid="tier-fill" className="absolute inset-y-0 left-0 rounded-full bg-text-tertiary" style={{ width: `${g.fillPct}%` }} />}
          {g.ticks.map((t) => (
            <div key={t.value} data-testid="tier-tick" className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-full bg-text-primary" style={{ left: `${t.pct}%` }} />
          ))}
        </div>
        <span className={cn("w-20 shrink-0 text-right font-mono text-xs tabular-nums", value === null ? "text-text-tertiary" : "text-text-primary")}>{valueText}</span>
      </div>
      <div className="flex gap-3 text-xs text-text-tertiary" aria-hidden>
        <div className="relative h-4 min-w-0 flex-1">
          {g.ticks.map((t) => (
            <span key={t.value} className="absolute -translate-x-1/2 font-mono tabular-nums" style={{ left: `${t.pct}%` }}>
              {format(t.value)}
            </span>
          ))}
        </div>
        <span className="w-20 shrink-0" />
      </div>
      {caption && <p className="text-xs text-text-tertiary">{caption}</p>}
    </div>
  );
}
