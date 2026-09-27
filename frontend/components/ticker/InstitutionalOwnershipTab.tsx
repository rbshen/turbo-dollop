"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useInstitutionalOwnership } from "@/lib/hooks/useInstitutionalOwnership";
import type { InstitutionalHolderOut, InstitutionalOwnershipQuarterOut } from "@/lib/api/types";
import { capXAxisTickInterval, computeNiceTicksRange } from "@/lib/charts";
import { fmtCompactMoney, fmtCompactNumber, fmtPct, fmtPlainPct, pnlClass } from "@/lib/format";

interface Props {
  ticker: string;
}

// Two stacked panels, never one dual-axis chart -- ownership % (0-100) and
// holder count (a raw integer that can run into the thousands) are on
// completely different scales, the same reasoning Market Breadth's own
// percent-vs-count split documents.
const OWNERSHIP_COLOR = "var(--color-chart-1)";
const HOLDER_COLOR = "var(--color-chart-4)";
const GRID_COLOR = "var(--color-border-subtle)";
const TICK = { fill: "var(--color-text-tertiary)", fontSize: 10 };
const CHART_HEIGHT = 200;

const SENTIMENT_TONE: Record<string, string> = {
  Accumulating: "text-positive",
  Distributing: "text-negative",
  Neutral: "text-text-tertiary",
};

function fmtQuarterLabel(year: number, quarter: number): string {
  return `${year} Q${quarter}`;
}

function fmtAsOfDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function CardShell({ children }: { children: React.ReactNode }) {
  return <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">{children}</div>;
}

function StatCard({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border-card bg-surface-2 p-4">
      <p className="text-xs font-medium uppercase tracking-widest text-text-tertiary">{label}</p>
      <p className="mt-1 font-mono text-xl font-semibold text-text-primary">{value}</p>
      {sub != null && <p className="mt-0.5 text-xs text-text-tertiary">{sub}</p>}
    </div>
  );
}

function PositionTile({ label, count, change }: { label: string; count: number; change: number | null }) {
  return (
    <div className="rounded-md border border-border-card bg-surface-2 p-3 text-center">
      <p className="text-[11px] uppercase tracking-wide text-text-tertiary">{label}</p>
      <p className="mt-0.5 font-mono text-lg font-semibold text-text-primary">{count}</p>
      {change != null && change !== 0 && (
        <p className={`text-xs ${pnlClass(change)}`}>{change > 0 ? `+${change}` : change}</p>
      )}
    </div>
  );
}

function TrendPanel({
  title,
  data,
  categories,
  dataKey,
  color,
  valueFormat,
  ticks,
}: {
  title: string;
  data: Record<string, unknown>[];
  categories: string[];
  dataKey: string;
  color: string;
  valueFormat: (v: number) => string;
  ticks: number[];
}) {
  const config: ChartConfig = { [dataKey]: { label: title, color } };
  const domain: [number, number] = [ticks[0] ?? 0, ticks[ticks.length - 1] ?? 1];

  return (
    <div className="rounded-lg border border-border-card bg-surface p-4">
      <p className="mb-2 text-xs uppercase tracking-widest text-text-tertiary">{title}</p>
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height: CHART_HEIGHT }} role="img" aria-label={`${title} over the last quarters`}>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID_COLOR} />
          <XAxis dataKey="category" tickLine={false} axisLine={false} interval={capXAxisTickInterval(categories.length)} tick={TICK} />
          <YAxis domain={domain} ticks={ticks} hide />
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value) => <span className="font-mono font-semibold tabular-nums text-text-primary">{valueFormat(Number(value))}</span>}
              />
            }
          />
          <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} />
        </LineChart>
      </ChartContainer>
    </div>
  );
}

function TrendCharts({ trend, quartersShown, quartersTotal }: { trend: InstitutionalOwnershipQuarterOut[]; quartersShown: number; quartersTotal: number }) {
  if (trend.length === 0) {
    return <p className="text-sm text-text-tertiary">No trend data available yet.</p>;
  }

  // `trend` is latest-first (see InstitutionalOwnershipOut); a left-to-right
  // time axis needs oldest-first.
  const chronological = [...trend].reverse();
  const categories = chronological.map((q) => fmtQuarterLabel(q.year, q.quarter));

  const pctValues = chronological.map((q) => q.ownership_percent).filter((v): v is number => v != null);
  const pctTicks = computeNiceTicksRange(0, Math.max(0, ...pctValues, 1), 4);
  const pctData = chronological.map((q, i) => ({ category: categories[i], ownership_percent: q.ownership_percent }));

  const holderValues = chronological.map((q) => q.investors_holding).filter((v): v is number => v != null);
  const holderTicks = computeNiceTicksRange(0, Math.max(0, ...holderValues, 1), 4);
  const holderData = chronological.map((q, i) => ({ category: categories[i], investors_holding: q.investors_holding }));

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Trend</h3>
        {quartersShown < quartersTotal && (
          <span className="text-xs text-text-tertiary">
            {quartersShown} of {quartersTotal} quarters shown
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TrendPanel title="Ownership %" data={pctData} categories={categories} dataKey="ownership_percent" color={OWNERSHIP_COLOR} valueFormat={fmtPlainPct} ticks={pctTicks} />
        <TrendPanel title="Holder count" data={holderData} categories={categories} dataKey="investors_holding" color={HOLDER_COLOR} valueFormat={(v) => v.toLocaleString()} ticks={holderTicks} />
      </div>
    </div>
  );
}

function HoldersTable({ holders }: { holders: InstitutionalHolderOut[] }) {
  if (holders.length === 0) {
    return <p className="text-sm text-text-tertiary">No institutional holders reported this quarter.</p>;
  }
  return (
    <Table className="text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="border-b border-border-card py-2 text-xs font-medium uppercase tracking-widest text-text-secondary">Investor</TableHead>
          <TableHead className="border-b border-border-card py-2 text-right text-xs font-medium uppercase tracking-widest text-text-secondary">Market Value</TableHead>
          <TableHead className="border-b border-border-card py-2 text-right text-xs font-medium uppercase tracking-widest text-text-secondary">Shares</TableHead>
          <TableHead className="border-b border-border-card py-2 text-right text-xs font-medium uppercase tracking-widest text-text-secondary">QoQ %</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {holders.map((h) => (
          <TableRow key={h.investor_name} className="hover:bg-surface-2/50">
            <TableCell className="border-b border-border-subtle py-2 text-text-primary">{h.investor_name}</TableCell>
            <TableCell className="border-b border-border-subtle py-2 text-right font-mono tabular-nums text-text-primary">
              {h.market_value != null ? fmtCompactMoney(h.market_value) : "—"}
            </TableCell>
            <TableCell className="border-b border-border-subtle py-2 text-right font-mono tabular-nums text-text-primary">
              {h.shares != null ? fmtCompactNumber(h.shares) : "—"}
            </TableCell>
            <TableCell className={`border-b border-border-subtle py-2 text-right font-mono tabular-nums ${h.market_value_change_pct != null ? pnlClass(h.market_value_change_pct) : "text-text-tertiary"}`}>
              {h.market_value_change_pct != null ? fmtPct(h.market_value_change_pct) : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function InstitutionalOwnershipTab({ ticker }: Props) {
  const { data, error, isLoading } = useInstitutionalOwnership(ticker);

  if (error) {
    return <p className="py-6 text-sm text-negative">Couldn&apos;t load Institutional Ownership — {error.message}</p>;
  }
  if (isLoading || !data) {
    return <p className="py-6 text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  if (!data.enabled) {
    return (
      <div className="py-6">
        <CardShell>
          <h2 className="font-heading text-sm font-semibold text-text-primary">Institutional Ownership</h2>
          <p className="text-sm text-text-secondary">
            Institutional ownership data is turned off (Settings &gt; Status). Turn on the &quot;Institutional
            ownership&quot; data group to see this tab.
          </p>
        </CardShell>
      </div>
    );
  }

  if (data.no_coverage) {
    return (
      <div className="py-6">
        <CardShell>
          <h2 className="font-heading text-sm font-semibold text-text-primary">Institutional Ownership</h2>
          <p className="text-sm text-text-secondary">
            No 13F institutional-ownership data found for {ticker} in any recent quarter.
          </p>
        </CardShell>
      </div>
    );
  }

  return (
    <div className="space-y-4 py-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="font-heading text-sm font-semibold text-text-primary">Institutional Ownership</h2>
          <p className="text-sm text-text-secondary">13F filings across institutional holders. Informational only.</p>
        </div>
        <p className="text-xs text-text-tertiary">
          As of {data.as_of_quarter}
          {data.as_of_date ? ` (${fmtAsOfDate(data.as_of_date)})` : ""}
          {data.fetched_at ? ` · fetched ${fmtAsOfDate(data.fetched_at)}` : ""}
        </p>
      </div>

      {data.data_stale_warning && (
        <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">
          This data hasn&apos;t refreshed in a while (last successful fetch was over 4 months ago) -- treat the
          figures below as dated.
        </p>
      )}

      {data.ownership_valid ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Institutional Ownership"
            value={data.ownership_percent != null ? fmtPlainPct(data.ownership_percent) : "—"}
            sub={data.ownership_percent_change != null ? <span className={pnlClass(data.ownership_percent_change)}>{fmtPct(data.ownership_percent_change)} QoQ</span> : undefined}
          />
          <StatCard
            label="13F Holders"
            value={data.holder_count ?? "—"}
            sub={data.holder_count_change != null && data.holder_count_change !== 0 ? (
              <span className={pnlClass(data.holder_count_change)}>{data.holder_count_change > 0 ? `+${data.holder_count_change}` : data.holder_count_change} QoQ</span>
            ) : undefined}
          />
          <StatCard
            label="Shares Held"
            value={data.shares_held != null ? fmtCompactNumber(data.shares_held) : "—"}
            sub={data.shares_outstanding != null ? `of ${fmtCompactNumber(data.shares_outstanding)} outstanding` : undefined}
          />
          <StatCard
            label="Sentiment"
            value={<span className={data.sentiment ? SENTIMENT_TONE[data.sentiment] : "text-text-tertiary"}>{data.sentiment ?? "—"}</span>}
            sub={data.sentiment_rising_count != null ? `${data.sentiment_rising_count} of last 4 quarters rising` : undefined}
          />
        </div>
      ) : (
        <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">{data.note}</p>
      )}

      {data.positions && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Positions This Quarter</h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <PositionTile label="Opened" count={data.positions.opened} change={data.positions.opened_change} />
            <PositionTile label="Increased" count={data.positions.increased} change={data.positions.increased_change} />
            <PositionTile label="Reduced" count={data.positions.reduced} change={data.positions.reduced_change} />
            <PositionTile label="Closed" count={data.positions.closed} change={data.positions.closed_change} />
          </div>
        </div>
      )}

      <TrendCharts trend={data.trend} quartersShown={data.trend_quarters_shown} quartersTotal={data.trend_quarters_total} />

      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Top Holders</h3>
        <HoldersTable holders={data.top_holders} />
      </div>
    </div>
  );
}
