"use client";

// The complete visual reference for the pill family -- every representation
// on one page, for review in the browser. Mock data only: nothing here calls
// the API (the hook-driven app components are rendered through their
// presentational views with props).
import type { ReactNode } from "react";

import { ScreenerCard } from "@/components/screener/ScreenerCard";
import { MomentumTable } from "@/components/momentum/MomentumTable";
import { CircularScoreBadge } from "@/components/overall/CircularScoreBadge";
import { OverallAssessmentView } from "@/components/overall/OverallAssessmentCard";
import { JobStatusPill } from "@/components/settings/ScheduledJobsSection";
import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { ChecklistCard } from "@/components/technical/ChecklistCard";
import { IndexMembershipPill } from "@/components/ticker/IndexMembershipPill";
import { PullbackPill } from "@/components/ticker/PullbackPill";
import { ReversalPill } from "@/components/ticker/ReversalPill";
import { TickerHeaderView } from "@/components/ticker/TickerHeader";
import { WeinsteinStagePill } from "@/components/ticker/WeinsteinStagePill";
import { WatchlistTable } from "@/components/watchlist/WatchlistTable";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Status, Verdict, type StatusTone } from "@/components/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type {
  CronJobHealthOut,
  MomentumSnapshotRowOut,
  SpeculativeGrowthOut,
  TickerScoreOut,
  TickerSummaryOut,
  TrendAnalysisOut,
  WatchlistOut,
  WatchlistRowOut,
} from "@/lib/api/types";
import type { OverallAssessment } from "@/lib/overallScore";
import { pillLabel, toneFor } from "@/lib/tierColor";

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

function Group({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-medium text-text-primary">{title}</h3>
      {note && <p className="mb-3 mt-1 max-w-3xl text-xs text-text-tertiary">{note}</p>}
      {!note && <div className="mb-3" />}
      {children}
    </div>
  );
}

function Row({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {label && <span className="w-20 shrink-0 text-xs text-text-tertiary">{label}</span>}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tones
// ---------------------------------------------------------------------------

const TONES: { tone: StatusTone; label: string }[] = [
  { tone: "strong", label: "Strong pass" },
  { tone: "positive", label: "Pass" },
  { tone: "warn", label: "Pass" },
  { tone: "warn", label: "Needs review" },
  { tone: "caution", label: "Pass with caution" },
  { tone: "negative", label: "Fail" },
  { tone: "speculative", label: "Speculative growth" },
  { tone: "neutral", label: "Not scored" },
];

const BADGE_TONES: { tone: BadgeTone; label: string }[] = [
  { tone: "strong", label: "92" },
  { tone: "positive", label: "83" },
  { tone: "warn", label: "72" },
  { tone: "caution", label: "74 ⚠" },
  { tone: "negative", label: "48" },
  { tone: "speculative", label: "Spec" },
  { tone: "neutral", label: "Bank" },
];

const SCORE_SAMPLES: { score: number; verdict: string }[] = [
  { score: 95, verdict: "Strong Pass" },
  { score: 83, verdict: "Pass" },
  { score: 72, verdict: "Pass" },
  { score: 74, verdict: "Pass with caution" },
  { score: 48, verdict: "Fail" },
];

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const SPECULATIVE: SpeculativeGrowthOut = {
  ticker: "PLTR",
  qualifies: true,
  company_type: "Standard",
  not_applicable_reason: null,
  moat: "narrow_moat",
  growth_rate_pct: 32.4,
  growth_basis: "revenue",
  trailing_revenue_growth_pct: 28,
  gross_margin_ttm_pct: 79,
  net_income_ttm: 120_000_000,
  cfo_ttm: 650_000_000,
  cfo_recent_direction: "turning_positive",
  cash_and_st_investments: 5_000_000_000,
  cash_runway_years: null,
  price_to_sales_ttm: 24,
  psg_ratio: 0.8,
  potential_fake_growth: true,
};

const TREND_PENDING = {
  weinstein_stage: "top",
  weinstein_stage_since_date: null,
  weinstein_stage_since_is_lower_bound: null,
  weinstein_ma_slope_pct: null,
  weinstein_vs_ma_pct: null,
  weinstein_params: null,
  pending: {
    direction: "decline",
    since_date: null,
    since_is_lower_bound: false,
    band_cushion_pct: null,
    typical_weekly_move_pct: null,
    eta: {},
  },
} as unknown as TrendAnalysisOut;

const HEADER_DATA: Pick<
  TickerSummaryOut,
  | "ticker"
  | "company_name"
  | "exchange"
  | "sector"
  | "industry"
  | "index_memberships"
  | "price"
  | "change"
  | "change_percent"
  | "quote_currency"
  | "reported_currency"
  | "fair_value_verdict"
  | "fair_value_price"
  | "fair_value_method"
  | "valuation_source"
  | "fair_value_reported_currency"
  | "perf_5y_vs_spy_status"
  | "perf_5y_insufficient_history"
  | "next_earnings_date"
> = {
  ticker: "AAPL",
  company_name: "Apple Inc.",
  exchange: "NASDAQ",
  sector: "Technology",
  industry: "Consumer Electronics",
  index_memberships: ["sp500", "nasdaq"],
  price: 258.4,
  change: 1.26,
  change_percent: 0.49,
  quote_currency: "USD",
  reported_currency: "USD",
  fair_value_verdict: "overvalued",
  fair_value_price: 182.4,
  fair_value_method: "DCF",
  valuation_source: "custom",
  fair_value_reported_currency: "TWD",
  perf_5y_vs_spy_status: "outperform",
  perf_5y_insufficient_history: false,
  next_earnings_date: "2026-10-29",
};

const HEADER_ACTIONS = (
  <>
    <Button variant="ghost" size="sm">
      Add to watchlist
    </Button>
    <Button variant="ghost" size="sm">
      Refresh
    </Button>
  </>
);

function HeaderSample() {
  return (
    <TickerHeaderView
      data={HEADER_DATA}
      assessment={<Status tone="strong">Strong pass</Status>}
      actions={HEADER_ACTIONS}
      moat="wide_moat"
      specGrowth={SPECULATIVE}
      trend={TREND_PENDING}
    />
  );
}

const SCREENER_CARD: TickerScoreOut = {
  ticker: "NVDA",
  company_name: "NVIDIA Corporation",
  sector: "Technology",
  industry: "Semiconductors",
  company_type: "Standard",
  is_etf: false,
  step1_score: 92,
  step1_verdict: "Strong Pass",
  step2_score: 88,
  step2_verdict: "Pass",
  step4_score: 90,
  step4_verdict: "Pass",
  step5_score: 85,
  step5_verdict: "Pass",
  moat: "wide_moat",
  moat_score: 95,
  overall_score: 92,
  overall_verdict: "Strong Pass",
  market_cap: 4_300_000_000_000,
  last_price: 176.42,
  quote_currency: "USD",
  reported_currency: "USD",
  pe_ratio: 52.1,
  beta: 1.7,
  valuation_verdict: "overvalued",
  valuation_source: "auto",
  growth_rate: 31.2,
  computed_at: "2026-09-28T02:00:00Z",
  perf_5y_vs_spy_pct: 140.2,
  perf_5y_vs_spy_status: "outperform",
  speculative_growth_qualifies: false,
  weinstein_stage: "advance",
  weinstein_stage_since_date: null,
  weinstein_stage_since_is_lower_bound: null,
  weinstein_ma_slope_pct: null,
  weinstein_vs_ma_pct: null,
  weinstein_pending_direction: null,
  reversal_status: "confirmed",
  pullback_status: "recovered",
  bb_rsi_entry_signal: null,
  warren_active_signal_kind: null,
  warren_last_buy_fired_at: null,
};

const YEARS = ["2021", "2022", "2023", "2024", "2025"];

function watchlistRow(overrides: Partial<WatchlistRowOut>): WatchlistRowOut {
  return {
    ticker: "AAPL",
    company_name: "Apple Inc.",
    sector: "Technology",
    exchange: "NASDAQ",
    years: YEARS,
    revenue: [366, 394, 383, 391, 416],
    net_income: [95, 100, 97, 94, 112],
    cfo: [104, 122, 110, 118, 127],
    moat: "wide_moat",
    valuation_verdict: "fair",
    valuation_source: "auto",
    step1_score: 92,
    step1_verdict: "Strong Pass",
    step2_score: 88,
    step2_verdict: "Pass",
    step4_score: 90,
    step4_verdict: "Pass",
    step5_score: 85,
    step5_verdict: "Pass",
    overall_score: 92,
    overall_verdict: "Strong Pass",
    market_cap: 3_850_000_000_000,
    quote_currency: "USD",
    reported_currency: "USD",
    pe_ratio: 34.2,
    beta: 1.1,
    perf_5y_vs_spy_pct: 12,
    perf_5y_vs_spy_status: "outperform",
    speculative_growth_qualifies: false,
    consensus_rating: "Buy",
    added_at: "2026-01-05T00:00:00Z",
    ...overrides,
  };
}

const WATCHLIST_ROWS: WatchlistRowOut[] = [
  watchlistRow({}),
  watchlistRow({
    ticker: "JPM",
    company_name: "JPMorgan Chase & Co.",
    sector: "Financial Services",
    moat: "narrow_moat",
    valuation_verdict: "undervalued",
    overall_score: 74,
    overall_verdict: "Pass with caution",
    step5_verdict: "Pass with caution",
    consensus_rating: "Hold",
  }),
  watchlistRow({
    ticker: "XOM",
    company_name: "Exxon Mobil Corporation",
    sector: "Energy",
    moat: "no_moat",
    valuation_verdict: "overvalued",
    overall_score: 61,
    overall_verdict: "Fail",
    consensus_rating: "Sell",
  }),
  watchlistRow({
    ticker: "NEWCO",
    company_name: "Unscored Newco Inc.",
    sector: "Technology",
    moat: null,
    valuation_verdict: null,
    overall_score: null,
    overall_verdict: null,
    consensus_rating: "N/A",
  }),
];

const WATCHLIST: WatchlistOut = {
  id: 0,
  name: "Sample",
  sort_field: "ticker",
  sort_direction: "asc",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tickers: WATCHLIST_ROWS.map((r) => ({ ticker: r.ticker, added_at: r.added_at })),
};

const MOMENTUM_ROWS: MomentumSnapshotRowOut[] = [
  { ticker: "NVDA", company_name: "NVIDIA Corporation", moat: "wide_moat", return_3mo: 0.214, return_6mo: 0.488, return_12mo: 1.02, composite_score: 0.64, rank: 1, overall_score: 92 },
  { ticker: "PLTR", company_name: "Palantir Technologies", moat: "narrow_moat", return_3mo: 0.182, return_6mo: 0.35, return_12mo: 0.91, composite_score: 0.52, rank: 2, overall_score: 78 },
  { ticker: "XYZ", company_name: "Momentum Without A Score", moat: "no_moat", return_3mo: 0.11, return_6mo: 0.2, return_12mo: 0.4, composite_score: 0.24, rank: 3, overall_score: null },
];

function overallResult(overrides: Partial<OverallAssessment>): OverallAssessment {
  return {
    status: "complete",
    score: 95,
    verdict: "Strong Pass",
    breakdown: [
      { key: "step1", label: "Financials", baseWeight: 0.25, effectiveWeight: 0.25, score: 92, verdict: "Strong Pass", status: "ok" },
      { key: "step2", label: "Growth Rate", baseWeight: 0.25, effectiveWeight: 0.25, score: 88, verdict: "Pass", status: "ok" },
      { key: "step4", label: "Profitability", baseWeight: 0.2, effectiveWeight: 0.2, score: 74, verdict: "Pass with caution", status: "ok" },
      { key: "step5", label: "Debt", baseWeight: 0.15, effectiveWeight: null, score: null, verdict: null, status: "exempt" },
      { key: "moat", label: "Economic Moat", baseWeight: 0.15, effectiveWeight: 0.3, score: 95, verdict: "Wide Moat", status: "ok" },
    ],
    incompleteSteps: [],
    failingSteps: [],
    cautionSteps: ["Profitability"],
    ...overrides,
  };
}

const JOB_STATUSES: { status: CronJobHealthOut["health_status"]; description: string; time: string; message: string | null }[] = [
  { status: "ok", description: "Nightly fundamentals fetch", time: "2:00 AM", message: null },
  { status: "failed", description: "Nightly trend calculation", time: "3:30 AM", message: "FMP returned 500 for 12 tickers" },
  { status: "overdue", description: "Nightly price-target snapshot", time: "4:10 AM", message: "No run in the last 36 hours" },
  { status: "skipped", description: "Nightly liquidity zone calculation", time: "4:40 AM", message: "skipped (group daily_prices off)" },
  { status: "unknown", description: "Nightly market breadth", time: "5:00 AM", message: null },
];

// ---------------------------------------------------------------------------
// The reference
// ---------------------------------------------------------------------------

export function PillReference() {
  return (
    <div className="flex flex-col gap-10">
      <Group
        title="Tones — regular and compact"
        note="Soft tinted fill (tone at 16%), tone-coloured text, no border. Regular is the default; compact is for dense tables only (Watchlist, Momentum). The amber tone appears twice: the 70–74 score band shows the backend's word “Pass”, and “Needs review” is the tone's name."
      >
        <div className="flex flex-col gap-3">
          <Row label="Regular">
            {TONES.map(({ tone, label }, i) => (
              <Status key={i} tone={tone}>
                {label}
              </Status>
            ))}
          </Row>
          <Row label="Compact">
            {TONES.map(({ tone, label }, i) => (
              <Status key={i} tone={tone} size="compact">
                {label}
              </Status>
            ))}
          </Row>
        </div>
      </Group>

      <Group
        title="Neutral variants"
        note="Neutral has no read to colour: no score, a stage that is neither bullish nor bearish, a fact about the ticker, or a job with nothing to report. Skipped and Unknown are told apart by their word."
      >
        <div className="flex flex-col gap-3">
          <Row label="Regular">
            <Status tone="neutral">Not scored</Status>
            <Status tone="neutral">Skipped</Status>
            <Status tone="neutral">Unknown</Status>
            <IndexMembershipPill memberships={["sp500", "nasdaq"]} />
            <IndexMembershipPill memberships={["dow"]} />
            <WeinsteinStagePill data={{ weinstein_stage: "base", weinstein_stage_since_date: null, weinstein_stage_since_is_lower_bound: null, weinstein_ma_slope_pct: null, weinstein_vs_ma_pct: null }} />
            <Badge tone="neutral">Common stock</Badge>
            <Badge missing />
          </Row>
          <Row label="Compact">
            <Status tone="neutral" size="compact">
              Not scored
            </Status>
            <Status tone="neutral" size="compact">
              Skipped
            </Status>
            <Status tone="neutral" size="compact">
              Unknown
            </Status>
            <Status tone="neutral" size="compact">
              S&amp;P 500 · Nasdaq
            </Status>
            <Badge size="compact" tone="neutral">
              Common stock
            </Badge>
            <Badge size="compact" missing />
          </Row>
        </div>
      </Group>

      <Group title="Direction glyph" note="A ▲ or ▼ sits inside the pill before the label; the label always says the state too.">
        <div className="flex flex-col gap-3">
          <Row label="Regular">
            <Status tone="positive" direction="up">
              +3.66%
            </Status>
            <Status tone="negative" direction="down">
              -1.20%
            </Status>
            <Status tone="strong" direction="up">
              +12.40%
            </Status>
          </Row>
          <Row label="Compact">
            <Status tone="positive" direction="up" size="compact">
              +3.66%
            </Status>
            <Status tone="negative" direction="down" size="compact">
              -1.20%
            </Status>
            <Status tone="strong" direction="up" size="compact">
              +12.40%
            </Status>
          </Row>
        </div>
      </Group>

      <Group
        title="Score + label"
        note="The number beside a pill is never coloured (text-primary, mono); the pill carries the tone. Inline, stacked above the pill (the real ScreenerCard ScoreBadge), and the score held inside a compact pill (the Watchlist Analysis cell)."
      >
        <div className="flex flex-col gap-5">
          <Row label="Inline">
            {SCORE_SAMPLES.map(({ score, verdict }) => (
              <span key={`${score}-${verdict}`} className="flex items-center gap-2 pr-4">
                <span className="font-mono text-sm tabular-nums text-text-primary">{score}</span>
                <Verdict tone={toneFor(score, verdict)}>{pillLabel(verdict)}</Verdict>
              </span>
            ))}
          </Row>
          <Row label="Stacked">
            <div className="flex flex-wrap items-start gap-8">
              {SCORE_SAMPLES.map(({ score, verdict }) => (
                <ScoreBadge key={`${score}-${verdict}`} score={score} verdict={verdict} />
              ))}
            </div>
          </Row>
          <Row label="Compact">
            {BADGE_TONES.filter((b) => b.tone !== "speculative" && b.tone !== "neutral").map(({ tone, label }) => (
              <Badge key={tone} size="compact" tone={tone}>
                {label}
              </Badge>
            ))}
            <Badge size="compact" tone="neutral">
              85
            </Badge>
            <Badge size="compact" missing />
          </Row>
        </div>
      </Group>

      <Group title="Badge tones — regular and compact" note="Badge is the same pill as Status, for a short value in a table cell or list, with a missing state (—).">
        <div className="flex flex-col gap-3">
          <Row label="Regular">
            {BADGE_TONES.map(({ tone, label }) => (
              <Badge key={tone} tone={tone}>
                {label}
              </Badge>
            ))}
            <Badge missing />
          </Row>
          <Row label="Compact">
            {BADGE_TONES.map(({ tone, label }) => (
              <Badge key={tone} tone={tone} size="compact">
                {label}
              </Badge>
            ))}
            <Badge size="compact" missing />
          </Row>
        </div>
      </Group>

      <Group
        title="Pullback and Reversal pills — every state"
        note="Both render through the shared pill. “No pullback” and “not present” show nothing at all (the common, unremarkable state), so they have no pill to display."
      >
        <div className="flex flex-col gap-3">
          <Row label="Pullback">
            <PullbackPill status="pending" />
            <PullbackPill status="recovered" />
            <PullbackPill status="invalidated" />
            <span className="text-xs text-text-tertiary">no_pullback → renders nothing</span>
          </Row>
          <Row label="Reversal">
            <ReversalPill status="confirmed" />
            <ReversalPill status="confirmed_stale" />
            <span className="text-xs text-text-tertiary">not_present → renders nothing</span>
          </Row>
        </div>
      </Group>

      <Group
        title="Technical-tab ChecklistCard chips — every tone"
        note="The status chip at the top right of each Technical-tab card takes a tone, not a class string."
      >
        <div className="grid gap-3 md:grid-cols-2">
          {TONES.filter((t, i) => !(t.tone === "warn" && i === 3)).map(({ tone, label }, i) => (
            <ChecklistCard key={i} title="Example checklist" statusLabel={label} statusTone={tone} blurb={`A card whose chip is the ${tone} tone.`} items={[]} disclaimer="Informational only." />
          ))}
        </div>
      </Group>

      <Group
        title="Overall Assessment — ring, headline pill and breakdown chips"
        note="The ring stroke carries the tone (no fill) and the number stays neutral. Beside it the headline verdict pill, then one pill per weighted step (label · weight · score); an exempt step is a neutral pill."
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-4">
            {SCORE_SAMPLES.map(({ score, verdict }) => (
              <CircularScoreBadge key={`${score}-${verdict}`} score={score} verdict={verdict} size={56} />
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <OverallAssessmentView result={overallResult({})} />
            <OverallAssessmentView
              result={overallResult({
                score: 74,
                verdict: "Pass with caution",
                failingSteps: ["Debt"],
                cautionSteps: ["Profitability"],
              })}
            />
          </div>
        </div>
      </Group>

      <Group
        title="In context — ticker header (full width, and a 320px column)"
        note="Six status pills plus the index chip when everything applies. Whole pills wrap to the next line, 8px apart; the Speculative growth pill keeps its info and warning icons with it, and the Stage pill shows ⚠ for a pending stage change. Mock data."
      >
        <div className="flex flex-col gap-4">
          <div className="border border-border-subtle px-4 pb-4">
            <HeaderSample />
          </div>
          <div className="max-w-[320px] border border-dashed border-border-subtle px-3 pb-3">
            <HeaderSample />
          </div>
        </div>
      </Group>

      <Group
        title="In context — Screener card with every pill"
        note="The maximum: the score's verdict pill, the kind badge, Moat, Valuation, 5Y vs SPY, Stage, Reversal and Pullback — 8 pills. (Real ScreenerCard, mock row; the card is a link.)"
      >
        <div className="max-w-xs">
          <ScreenerCard data={SCREENER_CARD} />
        </div>
      </Group>

      <Group
        title="In context — Watchlist rows (compact pills; Rating stays coloured text)"
        note="Real WatchlistTable, mock rows: all three pills; Pass with caution (⚠) with Hold; a Fail with No moat and Sell; and an unscored ticker with a missing score and N/A rating. Up to three compact pills per row (Moat, Value, Analysis)."
      >
        <WatchlistTable watchlist={WATCHLIST} rows={WATCHLIST_ROWS} sortRules={[]} onSortRulesChange={() => {}} />
      </Group>

      <Group title="In context — Momentum rows" note="Real MomentumTable, mock rows: two compact pills per row (Moat, Score); the last row has no score.">
        <MomentumTable rows={MOMENTUM_ROWS} />
      </Group>

      <Group
        title="In context — Scheduled Jobs status column"
        note="Success, Failed, Overdue, and the two neutral pills, Skipped and Unknown (real JobStatusPill; there is no legend, the words label themselves)."
      >
        <Table className="table-fixed">
          <colgroup>
            <col className="w-[45%]" />
            <col className="w-28" />
            <col className="w-28" />
            <col />
          </colgroup>
          <TableHeader>
            <TableRow className="h-9">
              <TableHead>Description</TableHead>
              <TableHead>Time</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Message</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {JOB_STATUSES.map((job) => (
              <TableRow key={job.status}>
                <TableCell className="whitespace-normal text-text-primary">{job.description}</TableCell>
                <TableCell className="font-mono text-xs tabular-nums text-text-secondary">{job.time}</TableCell>
                <TableCell>
                  <JobStatusPill status={job.status} />
                </TableCell>
                <TableCell
                  className={`whitespace-normal text-xs ${job.status === "failed" ? "text-negative" : job.status === "overdue" ? "text-warn" : "text-text-tertiary"}`}
                >
                  {job.message ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Group>
    </div>
  );
}
