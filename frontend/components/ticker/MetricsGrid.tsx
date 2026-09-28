import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { DefinitionRow, Section, SectionGrid } from "@/components/ui/section";
import { fmtCompactMoney, fmtCompactNumber, fmtNumber, fmtPct, fmtRatio } from "@/lib/format";
import type { MetricDef, MetricGroup } from "@/lib/metrics/config";
import type { OutlierWarning, TickerSummaryOut } from "@/lib/api/types";

const FLAG_TITLE = "Looks anomalous compared to trailing history — verify independently before relying on this number";
// Distinct icon from FLAG_TITLE's "⚠" -- a methodology caveat (this figure
// means something slightly different than usual), not a data-quality flag.
const TOOLTIP_ICON = "ⓘ";

function formatValue(value: TickerSummaryOut[keyof TickerSummaryOut], format: MetricDef["format"], quoteCurrency: string): string {
  if (value == null) return "—";
  if (format === "text") return typeof value === "string" ? value : "—";
  if (typeof value !== "number") return "—";
  // Every "compactMoney" field in lib/metrics/config.ts (market_cap,
  // enterprise_value, avg_dollar_volume_20d, week52_high/low) is
  // quote-domain -- derived from price/market cap, not a statement figure.
  if (format === "compactMoney") return fmtCompactMoney(value, quoteCurrency);
  if (format === "compactNumber") return fmtCompactNumber(value);
  if (format === "percent") return fmtPct(value);
  if (format === "ratio") return fmtRatio(value);
  return fmtNumber(value);
}

interface Props {
  groups: MetricGroup[];
  values: TickerSummaryOut;
  outlierWarnings?: OutlierWarning[];
}

interface StatColumnProps {
  groups: MetricGroup[];
  values: TickerSummaryOut;
  flaggedKeys: Set<string>;
}

// Each group renders as its own titled Section, stacked within its
// assigned column (see MetricGroup's `column` field in lib/metrics/
// config.ts) -- groups are never split across the two side-by-side
// columns. Every metric is a plain label/value pair (no headline-scale
// figure appears anywhere in this grid), so DefinitionRow is the right
// primitive for every group -- MetricTile is not used here.
function StatColumn({ groups, values, flaggedKeys }: StatColumnProps) {
  return (
    <div>
      {groups.map((group) => (
        <Section key={group.title} title={group.title}>
          {group.metrics.map((metric) => (
            <DefinitionRow
              key={metric.key}
              label={metric.label}
              value={
                <>
                  {formatValue(values[metric.key], metric.format, values.quote_currency)}
                  {flaggedKeys.has(metric.key) && (
                    <span className="ml-1.5 text-warn" title={FLAG_TITLE}>
                      ⚠
                    </span>
                  )}
                  {metric.tooltip && values[metric.tooltip.when] && (
                    <span className="ml-1.5 text-text-tertiary" title={metric.tooltip.text}>
                      {TOOLTIP_ICON}
                    </span>
                  )}
                </>
              }
            />
          ))}
        </Section>
      ))}
    </div>
  );
}

export function MetricsGrid({ groups, values, outlierWarnings = [] }: Props) {
  const flaggedKeys = new Set(outlierWarnings.map((w) => w.metric));
  const labels = Object.fromEntries(groups.flatMap((g) => g.metrics).map((m) => [m.key, m.label]));

  const leftGroups = groups.filter((g) => g.column === "left");
  const rightGroups = groups.filter((g) => g.column === "right");

  return (
    <div className="space-y-5">
      <SectionGrid>
        <StatColumn groups={leftGroups} values={values} flaggedKeys={flaggedKeys} />
        <StatColumn groups={rightGroups} values={values} flaggedKeys={flaggedKeys} />
      </SectionGrid>

      <OutlierWarningNote warnings={outlierWarnings} labels={labels} currency={values.reported_currency ?? "USD"} />
    </div>
  );
}
