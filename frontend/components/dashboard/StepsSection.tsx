"use client";

import type { ReactNode } from "react";

import { Sparkline } from "@/components/charts/Sparkline";
import { ThresholdGauge } from "@/components/charts/ThresholdGauge";
import { TierScale } from "@/components/charts/TierScale";
import { VisualRow } from "@/components/charts/VisualRow";
import { MiniBarChart } from "@/components/charts/MiniBarChart";
import { RowSkeleton } from "@/components/dashboard/Skeleton";
import { SectionHeading } from "@/components/dashboard/SectionHeading";
import { StepRow } from "@/components/dashboard/StepRow";
import { MOAT_TONE } from "@/components/ticker/MoatPill";
import { Section } from "@/components/ui/section";
import { Status } from "@/components/ui/status";
import type {
  DashboardDebt,
  DashboardFinancials,
  DashboardGrowth,
  DashboardMoat,
  DashboardOut,
  DashboardProfitability,
  DashboardRatioSeries,
} from "@/lib/api/types";
import { cfoNotScoredText, debtFormat, fmtMonthYear, fmtPct1, fmtPctWhole, growthBasisText } from "@/lib/dashboard";
import { fmtCompactMoney, fmtMoney } from "@/lib/format";
import { MOAT_LABELS, MOAT_NOT_RATED_NOTE } from "@/lib/overallScore";
import { pillLabel } from "@/lib/tierColor";

const Quiet = ({ children }: { children: ReactNode }) => <p className="text-xs text-text-tertiary">{children}</p>;

function lastValue(values: (number | null)[]): number | null {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] != null) return values[i];
  return null;
}

// --- Financials ----------------------------------------------------------------------------------------------------------------

function FinancialsVisual({ f, currency }: { f: DashboardFinancials; currency: string }) {
  if (!f.available) return <Quiet>No cached financial statements for this ticker yet</Quiet>;
  const { years } = f.series;
  const first = years[0];
  const last = years[years.length - 1];
  const charts = [
    { key: "revenue", label: "Revenue", values: f.series.revenue, scored: f.scored_revenue },
    { key: "net_income", label: "Net income", values: f.series.net_income, scored: f.scored_net_income },
    { key: "cfo", label: "Operating cash flow", values: f.series.cfo, scored: f.scored_cfo },
  ];
  const exempt = cfoNotScoredText(f.cfo_exempt_reason);
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-1 gap-x-4 gap-y-3 min-[480px]:grid-cols-3">
        {charts.map((c) => {
          const latest = lastValue(c.values);
          return (
            <div key={c.key} className="min-w-0" data-testid={`financials-${c.key}`} data-scored={c.scored}>
              <p className="mb-1 text-xs text-text-secondary">
                {c.label}
                {!c.scored && <span className="text-text-tertiary"> · not scored</span>}
              </p>
              <MiniBarChart categories={years} values={c.values} height={48} color={c.scored ? undefined : "var(--color-text-tertiary)"} />
              <p className="mt-1 font-mono text-xs tabular-nums text-text-primary">{latest != null ? fmtCompactMoney(latest, currency) : "—"}</p>
            </div>
          );
        })}
      </div>
      <Quiet>
        Last {years.length} completed fiscal years, FY{first} to FY{last}
        {exempt ? ` · ${exempt}` : ""}
      </Quiet>
    </div>
  );
}

// --- Growth --------------------------------------------------------------------------------------------------------------------

function GrowthVisual({ g }: { g: DashboardGrowth }) {
  if (!g.available || g.growth_rate == null) return <Quiet>No analyst estimates cached for this ticker</Quiet>;
  const max = (g.bands[g.bands.length - 1] ?? 15) + 5;
  const analysts = g.target_analyst_count != null ? `${g.target_analyst_count} analyst${g.target_analyst_count === 1 ? "" : "s"}` : "analysts";
  return (
    <TierScale
      value={g.growth_rate}
      max={max}
      bands={g.bands}
      format={fmtPctWhole}
      label="Expected growth rate"
      caption={`Expected ${growthBasisText(g.basis)} growth a year to FY${g.target_fiscal_year ?? "?"}, from ${analysts}`}
    />
  );
}

// --- Moat ----------------------------------------------------------------------------------------------------------------------

function MoatRow({ m, priceCurrency }: { m: DashboardMoat; priceCurrency: string }) {
  const pill = m.moat ? (
    <Status tone={MOAT_TONE[m.moat]}>{pillLabel(MOAT_LABELS[m.moat])}</Status>
  ) : (
    <Status tone="neutral">Not rated</Status>
  );
  const series = m.price_series;
  const closes = series.map((p) => p.close);
  return (
    <div className="border-t border-border-subtle py-4" data-testid="step-row-moat">
      <VisualRow label="Economic moat" pill={pill}>
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-text-tertiary">
            {m.rated ? "A manual rating: it multiplies the score, it is not a step" : `${MOAT_NOT_RATED_NOTE}`}
            {m.multiplier != null && ` (× ${m.multiplier.toFixed(2)})`}
          </p>
          {series.length >= 2 ? (
            <>
              <p className="text-xs text-text-secondary">{m.price_label}</p>
              <Sparkline
                values={closes}
                startLabel={fmtMonthYear(series[0].day)}
                endLabel={fmtMonthYear(series[series.length - 1].day)}
                format={(n) => fmtMoney(n, priceCurrency)}
                label={m.price_label}
              />
            </>
          ) : (
            <Quiet>{m.price_unavailable_reason ?? "No price history cached"}</Quiet>
          )}
        </div>
      </VisualRow>
    </div>
  );
}

// --- Profitability -------------------------------------------------------------------------------------------------------------

function RatioGauge({ name, series, cutoffs }: { name: string; series: DashboardRatioSeries; cutoffs: NonNullable<DashboardProfitability["cutoffs"]> }) {
  const body = (() => {
    if (series.exempt_reason) return <Quiet>Not applicable — {series.exempt_reason}</Quiet>;
    const scored = series.scored;
    if (scored?.basis === "negative_equity") {
      return <Quiet>Equity was negative in some period, so {name} is not used: it is scored on whether net income is positive and growing.</Quiet>;
    }
    if (!scored || scored.average == null) return <Quiet>No data</Quiet>;
    const latest = lastValue(series.values);
    const extras = [
      scored.recovery_excluded > 0 ? "an early dip already recovered from is left out" : null,
      scored.spike_excluded ? "one unusually high year is left out" : null,
    ].filter(Boolean);
    return (
      <ThresholdGauge
        value={scored.average}
        passLine={cutoffs.good}
        hardLimit={cutoffs.marginal}
        extraTicks={[cutoffs.excellent]}
        direction="floor"
        format={fmtPct1}
        label={`${name}, scored average`}
        caption={`Scored on the average of ${scored.points_used} years${latest != null ? ` (latest ${fmtPct1(latest)})` : ""}${extras.length ? `, ${extras.join(" and ")}` : ""} · good at ${fmtPctWhole(cutoffs.good)} or higher, excellent above ${fmtPctWhole(cutoffs.excellent)}, weak under ${fmtPctWhole(cutoffs.marginal)}`}
      />
    );
  })();
  return (
    <div className="min-w-0" data-testid={`profitability-${name.toLowerCase()}`}>
      <p className="mb-1 text-xs text-text-secondary">{name}</p>
      {body}
    </div>
  );
}

function ProfitabilityVisual({ p }: { p: DashboardProfitability }) {
  if (!p.available || !p.cutoffs) return <Quiet>Not enough cached data to show</Quiet>;
  return (
    <div className="flex flex-col gap-4">
      <RatioGauge name="ROE" series={p.roe} cutoffs={p.cutoffs} />
      <RatioGauge name="ROIC" series={p.roic} cutoffs={p.cutoffs} />
    </div>
  );
}

// --- Debt ----------------------------------------------------------------------------------------------------------------------

function DebtVisual({ d }: { d: DashboardDebt }) {
  if (!d.available) return <Quiet>Not enough cached data to show</Quiet>;
  if (d.status === "not_applicable") return <Quiet>Not applicable — {d.status_reason ?? "debt is not scored for this company"}</Quiet>;
  if (d.status === "insufficient_data" || d.ratios.length === 0) return <Quiet>Not scored: not enough cached data</Quiet>;
  const breached = d.ratios.filter((r) => d.unrescued_breaches.includes(r.key)).map((r) => r.label.toLowerCase());
  return (
    <div className="flex flex-col gap-4">
      {d.ratios.map((r) => (
        <div key={r.key} className="min-w-0" data-testid={`debt-${r.key}`}>
          <p className="mb-1 text-xs text-text-secondary">
            {r.label}
            {r.adjusted_value != null && <span className="text-text-tertiary"> · {debtFormat(r.unit)(r.adjusted_value)} without deferred revenue</span>}
          </p>
          {r.excluded ? (
            <Quiet>Excluded this period — operating cash flow is not positive, so its weight goes to the other ratios</Quiet>
          ) : r.tier === "negative_ebitda" ? (
            <p className="text-xs text-warn">Can&apos;t be calculated: EBITDA is negative, which counts as a breach</p>
          ) : (
            <ThresholdGauge
              value={r.value}
              passLine={r.pass_line}
              hardLimit={r.hard_limit}
              direction={r.direction === "floor" ? "floor" : "ceiling"}
              format={debtFormat(r.unit)}
              label={r.label}
            />
          )}
        </div>
      ))}
      {d.status === "partial" && d.status_reason && <Quiet>{d.status_reason}</Quiet>}
      {breached.length > 0 && <p className="text-xs text-warn">In breach: {breached.join(", ")}</p>}
    </div>
  );
}

// --- the section ---------------------------------------------------------------------------------------------------------------

export function StepsSection({ data, error, loading }: { data: DashboardOut | undefined; error: Error | undefined; loading: boolean }) {
  return (
    <Section
      title={<SectionHeading title="Five steps" tag="Scored" note="Each pill is the stored verdict, the same one the header and the Screener show." />}
      data-testid="dashboard-steps"
    >
      {error ? (
        <p className="text-sm text-negative">Couldn&apos;t load the steps — {error.message}</p>
      ) : loading || !data ? (
        <RowSkeleton rows={5} />
      ) : !data.has_data ? (
        <p className="text-sm text-text-secondary">Nothing is cached for this ticker yet, so there is nothing to show.</p>
      ) : (
        <div>
          <StepRow name="Financials" storedScore={data.financials.stored_score} storedVerdict={data.financials.stored_verdict}>
            <FinancialsVisual f={data.financials} currency={data.currency} />
          </StepRow>
          <StepRow name="Growth" storedScore={data.growth.stored_score} storedVerdict={data.growth.stored_verdict}>
            <GrowthVisual g={data.growth} />
          </StepRow>
          <MoatRow m={data.moat} priceCurrency={data.fair_value.currency} />
          <StepRow name="Profitability" storedScore={data.profitability.stored_score} storedVerdict={data.profitability.stored_verdict}>
            <ProfitabilityVisual p={data.profitability} />
          </StepRow>
          <StepRow name="Debt" storedScore={data.debt.stored_score} storedVerdict={data.debt.stored_verdict} kind="debt">
            <DebtVisual d={data.debt} />
          </StepRow>
        </div>
      )}
    </Section>
  );
}
