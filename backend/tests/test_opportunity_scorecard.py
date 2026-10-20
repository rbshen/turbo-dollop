"""The Scorecard's pure aggregation (scoring/opportunity_scorecard.py): the gate, the per-cohort medians, every exclusion with its count,
leveraged separation, overlapping rule groups, the pool baseline and the flag comparator. Synthetic data only; no database."""

import pytest

from scoring import opportunity_scorecard as sc
from scoring.opportunity_scorecard import Rec


def rec(cohort="2026-01-02", ticker="AAA", horizon=5, status="complete", tier="quality", list_name="momentum", leveraged=False, gap=False,
        ret=0.05, spy=0.01, ex=None, sector_ret=0.02, ex_sector=None, stop_hit=False, stop_fill=None, worst=-0.03, dd=-0.02, rules=()):
    if ret is None:
        spy = sector_ret = None
    ex = (ret - spy) if ex is None and ret is not None and spy is not None else ex
    ex_sector = (ret - sector_ret) if ex_sector is None and ret is not None and sector_ret is not None else ex_sector
    return Rec(cohort, ticker, horizon, status, tier, list_name, leveraged, gap, ret, spy, ex, sector_ret, ex_sector, stop_hit, stop_fill, worst, dd, rules)


def cohort_id(i):
    return f"2026-02-{i + 1:02d}"


def rows(cohort, n, **kw):
    return [rec(cohort=cohort, ticker=f"T{cohort[-2:]}{i}", **kw) for i in range(n)]


def build(listed_by_cohort, pool_by_cohort=None, weights=None):
    card = sc.Scorecard()
    for i, (cohort, recs) in enumerate(listed_by_cohort.items()):
        card.add_cohort(cohort, (weights or {}).get(cohort), recs, (pool_by_cohort or {}).get(cohort, []))
    return card


def group(card, key):
    return next(g for g in card.result() if g["key"] == key)


def cell(card, key, h=5, b="spy"):
    return group(card, key)["cells"][str(h)][b]


# --- the gate ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows_n,cohorts_n,state",
    [(19, 3, sc.TOO_EARLY), (60, 2, sc.TOO_EARLY), (20, 3, sc.EARLY), (59, 8, sc.EARLY), (60, 7, sc.EARLY), (60, 8, sc.OK), (200, 30, sc.OK), (0, 0, sc.TOO_EARLY)],
)
def test_gate_thresholds(rows_n, cohorts_n, state):
    assert sc.gate_state(rows_n, cohorts_n) == state


def test_cohort_count_is_the_binding_condition():
    # 100 complete rows in 2 cohorts: plenty of rows, but only two cohorts -> still too early, counts only.
    card = build({cohort_id(0): rows(cohort_id(0), 50), cohort_id(1): rows(cohort_id(1), 50)})
    c = cell(card, "momentum")
    assert c["n_complete"] == 100 and c["cohorts"] == 2 and c["state"] == sc.TOO_EARLY and c["values"] is None


def test_below_the_gate_shows_counts_only_and_no_pool_values():
    listed = {cohort_id(i): rows(cohort_id(i), 3) for i in range(2)}
    pool = {cohort_id(i): [rec(cohort=cohort_id(i), ticker=f"P{j}", ret=0.0) for j in range(40)] for i in range(2)}
    c = cell(build(listed, pool), "momentum")
    assert c["values"] is None and c["n_complete"] == 6
    assert c["pool"]["n_complete"] == 80 and c["pool"]["values"] is None  # the pool's figures stay hidden while the cell is gated
    assert c["listed_minus_pool"]["median_excess"] is None


def test_gate_states_with_synthetic_multi_cohort_data():
    def many(n_cohorts, per):
        return build({cohort_id(i): rows(cohort_id(i), per) for i in range(n_cohorts)})

    assert cell(many(3, 7), "momentum")["state"] == sc.EARLY  # 21 rows, 3 cohorts
    assert cell(many(3, 7), "momentum")["values"] is not None
    assert cell(many(8, 8), "momentum")["state"] == sc.OK  # 64 rows, 8 cohorts
    assert cell(many(3, 6), "momentum")["state"] == sc.TOO_EARLY  # 18 rows


# --- headline statistics ------------------------------------------------------------------------------------------------------------


def test_median_is_taken_per_cohort_then_across_cohorts():
    # Cohort 0: one name carries a huge excess (+1.00) and four are flat (0.00) -> cohort median 0. Cohort 1 and 2: every name +0.02.
    c0 = [rec(cohort=cohort_id(0), ticker=f"A{i}", ret=0.01 + (1.0 if i == 0 else 0.0), spy=0.01) for i in range(5)]
    c1 = [rec(cohort=cohort_id(1), ticker=f"B{i}", ret=0.03, spy=0.01) for i in range(5)]
    c2 = [rec(cohort=cohort_id(2), ticker=f"C{i}", ret=0.03, spy=0.01) for i in range(5)]
    # pad to reach the gate (20 rows) with the same cohort structure
    c3 = [rec(cohort=cohort_id(2), ticker=f"D{i}", ret=0.03, spy=0.01) for i in range(6)]
    c = cell(build({cohort_id(0): c0, cohort_id(1): c1, cohort_id(2): c2 + c3}), "momentum")
    v = c["values"]
    assert c["n_complete"] == 21 and c["cohorts"] == 3
    assert v["median_excess"] == pytest.approx(0.02)  # median of the cohort medians [0.00, 0.02, 0.02]
    assert v["mean_excess"] == pytest.approx((1.0 + 0.0 * 4 + 0.02 * 16) / 21)
    assert v["cohorts_positive"] == 2 and v["cohorts_counted"] == 3  # "2 of 3 cohorts positive"


def test_median_of_cohort_medians_differs_from_the_pooled_median():
    # Cohort 0 has 15 names at +0.10; cohorts 1 and 2 have 3 names each at -0.01. Pooled median is +0.10, per-cohort median is -0.01.
    c0 = [rec(cohort=cohort_id(0), ticker=f"A{i}", ret=0.11, spy=0.01) for i in range(15)]
    c1 = [rec(cohort=cohort_id(1), ticker=f"B{i}", ret=0.00, spy=0.01) for i in range(3)]
    c2 = [rec(cohort=cohort_id(2), ticker=f"C{i}", ret=0.00, spy=0.01) for i in range(3)]
    v = cell(build({cohort_id(0): c0, cohort_id(1): c1, cohort_id(2): c2}), "momentum")["values"]
    assert v["median_excess"] == pytest.approx(-0.01)
    assert v["share_above"] == pytest.approx(15 / 21)
    assert v["cohorts_positive"] == 1


def test_benchmark_median_and_stop_figures():
    listed = {
        cohort_id(i): [
            rec(cohort=cohort_id(i), ticker=f"T{i}{j}", ret=0.04, spy=0.01, stop_hit=(j % 2 == 0), stop_fill=-0.10 if j % 2 == 0 else None, worst=-0.12 if j % 2 == 0 else -0.02, dd=-0.05)
            for j in range(8)
        ]
        for i in range(3)
    }
    v = cell(build(listed), "momentum")["values"]
    assert v["benchmark_median_return"] == pytest.approx(0.01)
    assert v["stop_hit_rate"] == pytest.approx(0.5) and v["stop_n"] == 24
    # with-stop return: -0.10 for the hit half, +0.04 for the rest -> cohort median is the mean of the two middle values
    assert v["median_with_stop_return"] == pytest.approx((-0.10 + 0.04) / 2)
    assert v["median_with_stop_excess"] == pytest.approx((-0.11 + 0.03) / 2)
    assert v["median_worst_move"] == pytest.approx((-0.12 + -0.02) / 2) and v["median_drawdown"] == pytest.approx(-0.05)


def test_with_stop_return_is_derived_not_stored():
    assert sc.with_stop_return(rec(stop_hit=True, stop_fill=-0.15, ret=0.20)) == -0.15
    assert sc.with_stop_return(rec(stop_hit=False, ret=0.20)) == 0.20
    assert sc.with_stop_return(rec(stop_hit=None, ret=0.20)) is None  # a pool row has no stop


# --- exclusions, each with its count ---------------------------------------------------------------------------------------------


def test_each_exclusion_is_counted_and_left_out_of_the_statistics():
    listed = {}
    for i in range(3):
        c = cohort_id(i)
        listed[c] = (
            rows(c, 7, ret=0.05, spy=0.01)  # 7 complete, excess +0.04
            + [rec(cohort=c, ticker=f"P{i}", status="pending", ret=None, ex=None, ex_sector=None)]
            + [rec(cohort=c, ticker=f"C{i}", status="censored", ret=-0.50, spy=0.0)]  # delisted: stored last-bar return, excess -0.50
            + [rec(cohort=c, ticker=f"G{i}", gap=True, ret=0.90, spy=0.01)]  # entry gap: any status, left out
            + [rec(cohort=c, ticker=f"L{i}", leveraged=True, ret=0.30, spy=0.01)]  # leveraged: its own row
        )
    card = build(listed)
    c = cell(card, "momentum")
    assert (c["n_complete"], c["n_pending"], c["n_censored"], c["n_entry_gap"]) == (21, 3, 3, 3)
    assert c["values"]["median_excess"] == pytest.approx(0.04) and c["values"]["mean_excess"] == pytest.approx(0.04)
    # sensitivity line: with the censored rows (-0.50) included, per cohort the median of [0.04 x7, -0.50] is still 0.04, but the row count shows
    assert c["values"]["including_censored"]["n"] == 24
    lev = cell(card, "momentum:leveraged")
    assert lev["n_complete"] == 3 and lev["state"] == sc.TOO_EARLY


def test_sensitivity_line_moves_when_censored_rows_are_many():
    listed = {
        cohort_id(i): rows(cohort_id(i), 4, ret=0.05, spy=0.01) + [rec(cohort=cohort_id(i), ticker=f"C{i}{j}", status="censored", ret=-0.60, spy=0.0) for j in range(6)]
        for i in range(6)
    }
    v = cell(build(listed), "momentum")["values"]
    assert v["median_excess"] == pytest.approx(0.04)
    assert v["including_censored"]["median_excess"] == pytest.approx(-0.60)  # dropping the delistings flatters the headline


def test_complete_row_without_a_sector_return_is_counted_apart():
    listed = {cohort_id(i): [rec(cohort=cohort_id(i), ticker=f"E{j}", tier="etf", sector_ret=None, ex_sector=None) for j in range(9)] for i in range(3)}
    card = build(listed)
    assert cell(card, "momentum:etf", b="sector")["n_complete"] == 0
    assert cell(card, "momentum:etf", b="sector")["n_no_benchmark"] == 27
    assert cell(card, "momentum:etf", b="spy")["n_complete"] == 27


# --- leveraged, overlapping rule groups, pool ------------------------------------------------------------------------------------------


def test_leveraged_etfs_never_enter_the_etf_tier_or_the_list():
    c = cohort_id(0)
    recs = [rec(cohort=c, ticker="ETF1", tier="etf", list_name="reversal"), rec(cohort=c, ticker="SOXL", tier="etf", list_name="reversal", leveraged=True)]
    card = build({c: recs})
    assert cell(card, "reversal:etf")["n_complete"] == 1
    assert cell(card, "reversal")["n_complete"] == 1
    assert cell(card, "reversal:leveraged")["n_complete"] == 1
    assert not any(g["key"] == "momentum:leveraged" for g in card.result())  # no leveraged row where none was listed


def test_rule_groups_overlap_and_are_never_summed():
    c = cohort_id(0)
    recs = [
        rec(cohort=c, ticker="X", list_name="reversal", rules=("B2", "B3")),
        rec(cohort=c, ticker="Y", list_name="reversal", rules=("B2",)),
        rec(cohort=c, ticker="Z", list_name="reversal", rules=("B1",)),
        rec(cohort=c, ticker="M", list_name="momentum", rules=("deep_pullback",)),
    ]
    card = build({c: recs})
    n = {k: cell(card, f"rule:{k}")["n_complete"] for k in sc.RULE_CUTS}
    assert n == {"B1": 1, "B2": 2, "B3": 1, "deep_pullback": 1}
    rows_listed = cell(card, "reversal")["n_complete"] + cell(card, "momentum")["n_complete"]
    assert rows_listed == 4 and sum(n.values()) == 5  # the cuts overlap: summing them would count a row twice
    assert all(g["cells"]["5"]["spy"]["pool"] is None for g in card.result() if g["kind"] == "rule")
    assert not any(g["key"] in ("rule", "rules", "rule:all", "rule:total") for g in card.result())


def test_pool_baseline_matches_list_and_tier():
    listed = {cohort_id(i): rows(cohort_id(i), 8, tier="quality", list_name="reversal", ret=0.06, spy=0.01) for i in range(3)}
    pool = {}
    for i in range(3):
        c = cohort_id(i)
        pool[c] = (
            [rec(cohort=c, ticker=f"Q{j}", tier="quality", list_name="reversal", ret=0.02, spy=0.01) for j in range(10)]  # the match: +0.01
            + [rec(cohort=c, ticker=f"M{j}", tier="momentum_only", list_name="reversal", ret=0.30, spy=0.01) for j in range(10)]  # wrong tier
            + [rec(cohort=c, ticker=f"R{j}", tier="quality", list_name="momentum", ret=0.30, spy=0.01) for j in range(10)]  # wrong stage list
            + [rec(cohort=c, ticker=f"N{j}", tier="quality", list_name=None, ret=0.30, spy=0.01) for j in range(10)]  # stage allowed neither
            + [rec(cohort=c, ticker=f"L{j}", tier="quality", list_name="reversal", leveraged=True, ret=0.30, spy=0.01) for j in range(10)]
        )
    card = build(listed, pool)
    cq = cell(card, "reversal:quality")
    assert cq["pool"]["n_complete"] == 30 and cq["pool"]["cohorts"] == 3
    assert cq["pool"]["values"]["median_excess"] == pytest.approx(0.01)
    assert cq["listed_minus_pool"]["median_excess"] == pytest.approx(0.04)
    # the list-level baseline is every pool name the stage sent to Reversal (any tier, ordinary): 10 quality + 10 momentum_only per cohort
    assert cell(card, "reversal")["pool"]["n_complete"] == 60


def test_weights_note_only_on_cells_that_hold_quality_rows_from_more_than_one_version():
    listed = {
        cohort_id(0): rows(cohort_id(0), 8, tier="quality") + rows(cohort_id(0), 8, tier="momentum_only"),
        cohort_id(1): rows(cohort_id(1), 8, tier="quality") + rows(cohort_id(1), 8, tier="momentum_only"),
    }
    card = build(listed, weights={cohort_id(0): 8, cohort_id(1): 9})
    q = cell(card, "momentum:quality")
    assert q["mixed_weights"] is True and q["weights_versions"] == [8, 9]
    assert cell(card, "momentum:momentum_only")["mixed_weights"] is False
    same = build(listed, weights={cohort_id(0): 9, cohort_id(1): 9})
    assert cell(same, "momentum:quality")["mixed_weights"] is False and cell(same, "momentum:quality")["weights_versions"] == [9]


def test_empty_input_gives_zeroed_cells_not_an_error():
    result = sc.Scorecard().result()
    assert [g["key"] for g in result][:3] == ["momentum", "momentum:quality", "momentum:momentum_only"]
    c = result[0]["cells"]["60"]["sector"]
    assert c["n_complete"] == 0 and c["state"] == sc.TOO_EARLY and c["values"] is None


def test_group_order_is_list_then_tier_then_rule_cuts():
    keys = [g["key"] for g in build({cohort_id(0): [rec(cohort=cohort_id(0), list_name="reversal", leveraged=True, tier="etf")]}).result()]
    assert keys == [
        "momentum", "momentum:quality", "momentum:momentum_only", "momentum:etf",
        "reversal", "reversal:quality", "reversal:momentum_only", "reversal:etf", "reversal:leveraged",
        "rule:B1", "rule:B2", "rule:B3", "rule:deep_pullback",
    ]


# --- flags ------------------------------------------------------------------------------------------------------------------------


def flag_cohort(cohort="2026-02-01", open_=False, weights=8, eligible=None, not_covered=None, incomplete=None, flags=(), flag_recs=None, listed=None):
    return sc.FlagCohort(cohort, open_, weights, eligible or {}, not_covered or {}, incomplete or {}, list(flags), flag_recs or {}, listed or {})


def finfo(fid, cohort, ticker, trigger, flag_date="2026-02-03", at_ma=None):
    return sc.FlagInfo(fid, cohort, ticker, trigger, "momentum", "quality", flag_date, at_ma)


def test_flag_denominators_exclude_not_covered_and_incomplete():
    c = "2026-02-01"
    listed = {t: [rec(cohort=c, ticker=t, ret=0.01, spy=0.01)] for t in ("A", "B", "C", "D", "E", "F")}
    fc = flag_cohort(
        c,
        eligible={"D1": set("ABCDEF")},
        not_covered={"D1": {"C", "D", "ZZZ"}},  # ZZZ is not eligible: ignored
        incomplete={"D1": {"E", "A"}},  # A flagged anyway: it counts as flagged, not incomplete
        flags=[finfo(1, c, "A", "D1"), finfo(2, c, "B", "D1")],
        flag_recs={1: [rec(cohort=c, ticker="A", ret=0.2)], 2: [rec(cohort=c, ticker="B", ret=0.2)]},
        listed=listed,
    )
    d1 = sc.build_flag_section([fc])["triggers"]["D1"]
    assert (d1["eligible"], d1["flagged"], d1["not_covered"], d1["incomplete"], d1["unflagged"]) == (6, 2, 2, 1, 1)
    assert d1["per_cohort"][0]["unflagged"] == 1
    # the comparator holds exactly the one remaining name (F), priced from the list
    assert d1["cells"]["5"]["spy"]["unflagged"]["n_complete"] == 1


def test_flagged_and_unflagged_are_separate_and_triggers_are_not_summed():
    c = "2026-02-01"
    fc = flag_cohort(c, eligible={"D2": {"A", "B"}, "D3": {"A", "C"}}, flags=[finfo(1, c, "A", "D2"), finfo(2, c, "A", "D3")],
                     flag_recs={1: [rec(cohort=c, ticker="A", ret=0.1)], 2: [rec(cohort=c, ticker="A", ret=0.1)]}, listed={})
    out = sc.build_flag_section([fc])
    assert out["triggers"]["D2"]["flagged"] == 1 and out["triggers"]["D3"]["flagged"] == 1
    assert out["any_flag"]["flagged_names"] == 1  # the same name flagged twice counts once in the "any flag" view
    assert "total" not in out["triggers"] and "all" not in out["triggers"]


def test_any_flag_keeps_the_first_flag_of_a_name():
    c = "2026-02-01"
    fa = finfo(1, c, "A", "D3", "2026-02-05")
    fb = finfo(2, c, "A", "D2", "2026-02-03")
    fc = flag_cohort(c, flags=[fa, fb], flag_recs={1: [rec(cohort=c, ticker="A", ret=0.5, horizon=5)], 2: [rec(cohort=c, ticker="A", ret=0.1, horizon=5)]})
    cells = sc.build_flag_section([fc])["any_flag"]["cells"]["5"]["spy"]["flagged"]
    assert cells["n_complete"] == 1  # one row: the 02-03 D2 flag's, not the later D3's
    assert sc._first_flags([fa, fb])[0].trigger == "D2"


def test_window_open_cohorts_are_marked_and_the_comparator_is_provisional():
    a, b = "2026-02-01", "2026-02-08"
    closed = flag_cohort(a, open_=False, eligible={"D3": {"A", "B"}}, flags=[finfo(1, a, "A", "D3")], flag_recs={1: [rec(cohort=a, ticker="A")]}, listed={})
    still_open = flag_cohort(b, open_=True, eligible={"D3": {"C", "D"}}, flags=[finfo(2, b, "C", "D3")], flag_recs={2: [rec(cohort=b, ticker="C")]}, listed={})
    d3 = sc.build_flag_section([closed, still_open])["triggers"]["D3"]
    assert d3["cohorts"] == 2 and d3["cohorts_window_open"] == 1 and d3["flagged_in_open_cohorts"] == 1
    assert d3["comparator_provisional"] is True
    assert [p["window_open"] for p in d3["per_cohort"]] == [False, True]
    only_closed = sc.build_flag_section([closed])["triggers"]["D3"]
    assert only_closed["comparator_provisional"] is False and only_closed["cohorts_window_open"] == 0


def test_d3_splits_by_already_at_the_ma_on_the_list_date():
    c = "2026-02-01"
    flags = [finfo(1, c, "A", "D3", at_ma=True), finfo(2, c, "B", "D3", at_ma=True), finfo(3, c, "C", "D3", at_ma=False)]
    recs = {i: [rec(cohort=c, ticker="x", ret=0.1 * i, spy=0.0)] for i in (1, 2, 3)}
    d3 = sc.build_flag_section([flag_cohort(c, eligible={"D3": {"A", "B", "C"}}, flags=flags, flag_recs=recs)])["triggers"]["D3"]
    assert d3["split"]["already_at_ma_on_list"]["flagged"] == 2 and d3["split"]["not_at_ma_on_list"]["flagged"] == 1
    assert d3["split"]["already_at_ma_on_list"]["cells"]["5"]["spy"]["flagged"]["n_complete"] == 2
    assert d3["split"]["not_at_ma_on_list"]["cells"]["5"]["spy"]["flagged"]["n_complete"] == 1
    assert "split" not in sc.build_flag_section([flag_cohort(c)])["triggers"]["D1"]


def test_a_flag_without_outcome_rows_is_counted_as_unpriced():
    c = "2026-02-01"
    fc = flag_cohort(c, eligible={"D1": {"A", "B"}}, flags=[finfo(1, c, "A", "D1"), finfo(2, c, "B", "D1")], flag_recs={1: [rec(cohort=c, ticker="A", status="pending", ret=None)]})
    cell_ = sc.build_flag_section([fc])["triggers"]["D1"]["cells"]["5"]["spy"]["flagged"]
    assert cell_["n_pending"] == 1 and cell_["n_unpriced"] == 1


def test_flag_cells_are_gated_like_the_rest():
    cohorts = []
    for i in range(3):
        c = cohort_id(i)
        flags = [finfo(i * 10 + j, c, f"T{j}", "D3") for j in range(7)]
        cohorts.append(flag_cohort(c, eligible={"D3": {f"T{j}" for j in range(7)}}, flags=flags, flag_recs={f.flag_id: [rec(cohort=c, ticker=f.ticker, ret=0.05, spy=0.01)] for f in flags}))
    d3 = sc.build_flag_section(cohorts)["triggers"]["D3"]["cells"]["5"]["spy"]["flagged"]
    assert d3["state"] == sc.EARLY and d3["values"]["median_excess"] == pytest.approx(0.04)
    assert sc.build_flag_section(cohorts[:2])["triggers"]["D3"]["cells"]["5"]["spy"]["flagged"]["values"] is None
