import { fmtPlainPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ChartLegendItem {
  key: string;
  label: string;
  color: string;
  /** 0-100 -- shown next to the label when provided (pie/donut legends). */
  percent?: number;
}

interface Props {
  items: ChartLegendItem[];
  /** "row" wraps horizontally below a chart (stacked/grouped bars); "column"
   * stacks vertically beside a chart (donut/pie). */
  layout?: "row" | "column";
  className?: string;
}

export function ChartLegend({ items, layout = "row", className }: Props) {
  return (
    <div
      className={cn(
        "flex gap-x-4 gap-y-1.5 text-xs",
        layout === "row" ? "flex-wrap items-center justify-center" : "flex-col",
        className
      )}
    >
      {items.map((item) => (
        <div key={item.key} className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: item.color }} />
          <span className="truncate text-text-secondary">{item.label}</span>
          {item.percent != null && (
            <span className="font-mono tabular-nums text-text-tertiary">{fmtPlainPct(item.percent, 0)}</span>
          )}
        </div>
      ))}
    </div>
  );
}
