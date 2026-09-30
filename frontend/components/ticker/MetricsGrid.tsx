import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { DefinitionRow, Section, SectionGrid } from "@/components/ui/section";
import { currencyPrefix, fmtCompactMoney, fmtCompactNumber, fmtNumber, fmtPct, fmtRatio } from "@/lib/format";
import type { MetricDef, MetricGroup } from "@/lib/metrics/config";
import type { OutlierWarning, TickerSummaryOut } from "@/lib/api/types";

const FLAG_TITLE = "Looks anomalous compared to trailing history — verify independently before relying on this number";
// Distinct icon from FLAG_TITLE's "⚠" -- a methodology caveat (this figure
// means something slightly different than usual), not a data-quality flag.
const TOOLTIP_ICON = "ⓘ";

function formatValue(value: TickerSummaryOut[keyof TickerSummaryOut], format: MetricDef["format"], currency: string): string {
  if (value == null) return "—";
  if (format === "text") return typeof value === "string" ? value : "—";
  if (typeof value !== "number") return "—";
  // "compactMoney" fields default to the quote currency (market_cap,
  // avg_dollar_volume_20d, week52_high/low -- derived from price/market cap);
  // a metric marked `currency: "reported"` (enterprise_value) is a statement
  // figure and is passed the reporting currency by the caller instead.
  if (format === "compactMoney") return fmtCompactMoney(value, currency);
  if (format === "compactNumber") return fmtCompactNumber(value);
  if (format === "percent") return fmtPct(value);
  if (format === "ratio") return fmtRatio(value);
  return fmtNumber(value);
}

/** The currency a metric's money value is denominated in, per its `currency`
 * domain. A missing reported_currency falls back to the quote currency. */
function metricCurrency(metric: MetricDef, values: TickerSummaryOut): string {
  return metric.currency === "reported" ? (values.reported_currency ?? values.quote_currency) : values.quote_currency;
}

/** ISO code to show beside a money value that is NOT in the quote currency
 * (no forced USD conversion -- the currency is made explicit instead).
 * Null when nothing extra is needed: a quote-currency value, or a currency
 * whose prefix already spells out its code (currencyPrefix's "<CODE> "
 * fallback, e.g. "TWD 76.71T"). */
function foreignCurrencyCode(metric: MetricDef, values: TickerSummaryOut): string | null {
  if (metric.format !== "compactMoney") return null;
  const currency = metricCurrency(metric, values);
  if (currency === values.quote_currency) return null;
  return currencyPrefix(currency).startsWith(currency) ? null : currency;
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
                  {formatValue(values[metric.key], metric.format, metricCurrency(metric, values))}
                  {values[metric.key] != null && foreignCurrencyCode(metric, values) && (
                    <span className="ml-1 text-xs text-text-tertiary" title={`Reported in ${metricCurrency(metric, values)}, not converted to ${values.quote_currency}`}>
                      {metricCurrency(metric, values)}
                    </span>
                  )}
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
