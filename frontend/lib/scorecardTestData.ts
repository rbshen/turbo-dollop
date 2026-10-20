import type { ScorecardCell, ScorecardGroup, ScorecardOut } from "@/lib/api/types";

// Fixtures for the Scorecard tests (lib/scorecard.test.ts, app/opportunities/page.scorecard.test.tsx). Not imported by app code.

export function cell(over: Partial<ScorecardCell> = {}): ScorecardCell {
  return {
    n_complete: 0, n_pending: 0, n_censored: 0, n_entry_gap: 0, n_no_benchmark: 0, cohorts: 0, cohorts_total: 0, state: "too_early",
    values: null, weights_versions: [], mixed_weights: false, pool: null, listed_minus_pool: null, ...over,
  };
}

export function group(key: string, over: Partial<ScorecardGroup> = {}, c: Partial<ScorecardCell> = {}): ScorecardGroup {
  const base = cell(c);
  const cells = Object.fromEntries([5, 10, 20, 60].map((h) => [String(h), { spy: base, sector: base }]));
  return { key, kind: "list", list_name: "momentum", tier: null, rule: null, has_pool: true, cells, ...over };
}

export function out(over: Partial<ScorecardOut> = {}): ScorecardOut {
  return {
    has_data: true,
    versions: { selected: { rules: "2", triggers: "1", weights: null, current_rules: "2", current_triggers: "1" }, available: { rules: ["2"], triggers: ["1"], weights: [8, 9] } },
    latest: { outcomes_spy_bar: "2026-10-19", flags_session: "2026-10-19", latest_outcome_run_id: 13, latest_daily_run_id: 9 },
    thresholds: { min_rows: 20, min_cohorts: 3, early_rows: 60, early_cohorts: 8 },
    horizons: [5, 10, 20, 60],
    benchmarks: ["spy", "sector"],
    excluded: { other_rules_version_rows: 0, other_rules_version_pool_rows: 0, cohorts_other_weights_version: 0, by_horizon: {}, note: "" },
    next_expected: { "5": "2026-10-26" },
    cohorts: [
      { as_of_date: "2026-10-09", run_id: 1, rules_version: "2", weights_version: 8, listed_rows: 79, pool_names: 516, horizons: { "5": { complete: 79, pending: 0, censored: 0, expected_data_date: null } } },
      { as_of_date: "2026-10-16", run_id: 2, rules_version: "2", weights_version: 9, listed_rows: 99, pool_names: 497, horizons: { "5": { complete: 0, pending: 99, censored: 0, expected_data_date: "2026-10-26" } } },
    ],
    groups: [group("momentum", {}, { n_complete: 55, cohorts: 1, cohorts_total: 2, n_pending: 40 })],
    ...over,
  };
}

