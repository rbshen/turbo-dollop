"""data/opportunity_data.py: the weekly run end to end over a throwaway database and synthetic cached bars -- tiers, both lists,
the gate's edge cases, the frozen inputs and tags, and insert-only persistence (create, no-op rerun, --force in one transaction)."""

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import data.opportunity_data as od
from core.models import (
    EtfScreenerRow,
    MarketBreadthSnapshot,
    OpportunityOutcome,
    OpportunityPick,
    OpportunityPoolRow,
    OpportunityRun,
    OpportunitySnapshotRow,
    SharedBarsCache,
    TickerScore,
    TrendAnalysis,
    WarrenSignalEvent,
)
from scoring import opportunity_rules as rules

AS_OF = date(2026, 10, 9)
NOW = datetime(2026, 10, 10, 4, 0)
N_BARS = 600


def frame(drift: float, n: int = N_BARS, end: date = AS_OF, volume: float = 1e6, start: float = 50.0) -> pd.DataFrame:
    index = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    close = start * np.exp(drift * np.arange(n))
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": np.full(n, volume)}, index=index)


def recovering(n: int = N_BARS) -> pd.DataFrame:
    """A 33% drawdown from the 52-week high that has based (a trough 120 sessions ago, a higher low since) and turned up, with a
    30-week EMA whose slope is rising and above -2%: passes the B2 price structure for every tier."""
    df = frame(0.0, n)
    close = np.empty(n)
    close[: n - 250] = np.linspace(80, 200, n - 250)
    close[n - 250 : n - 120] = np.linspace(200, 120, 130)
    close[n - 120 :] = np.linspace(120, 135, 120)
    df["open"], df["close"] = close, close
    df["high"], df["low"] = close * 1.01, close * 0.99
    return df


# ticker -> (bars, tier hint, verdict, stage, weeks in advance, vs_ma, slope, rs)
def score(ticker: str, verdict: str | None, steps: float = 80.0, overall: int = 80, sector: str = "Technology", **kw) -> TickerScore:
    return TickerScore(
        ticker=ticker, company_name=f"{ticker} Inc", sector=sector, overall_verdict=verdict, overall_score=overall, steps_score=steps,
        moat="wide_moat", moat_multiplier=1.0, step1_score=90, step1_verdict="Pass", step2_score=90, step2_verdict="Pass",
        step4_score=90, step4_verdict="Pass", step5_score=90, step5_verdict="Pass", formula_version=6, weights_version=1,
        computed_at=NOW, **kw,
    )


def trend(ticker: str, stage: str = "advance", weeks: int = 20, vs_ma: float = 8.0, slope: float = 1.0, rs: float = 3.0, **kw) -> TrendAnalysis:
    return TrendAnalysis(
        ticker=ticker, computed_at=NOW, bars_as_of=AS_OF, weinstein_stage=stage,
        weinstein_stage_since_date=AS_OF - timedelta(weeks=weeks), weinstein_ma_slope_pct=slope, weinstein_vs_ma_pct=vs_ma,
        weinstein_mansfield_rs=rs, **kw,
    )


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(od, "engine", engine)

    frames: dict[str, pd.DataFrame] = {}
    stocks: list[str] = []
    etfs: list[str] = []
    monitored: list[str] = []

    with Session(engine) as s:
        def stock(ticker, drift, verdict, tr=None, sc=None, bars=None):
            frames[ticker] = bars if bars is not None else frame(drift)
            stocks.append(ticker)
            s.add(sc or score(ticker, verdict, overall=80 if verdict in ("Pass", "Strong Pass") else 55, steps=80.0 if verdict == "Fail" else 85.0))
            s.add(tr or trend(ticker))

        # Quality, momentum trend: list A without any rank
        stock("QUAL", 0.0008, "Pass")
        # Momentum-only, top-ranked, clean: list A
        stock("MOM1", 0.0013, "Fail")
        # Momentum-only, ranked 1st but extended (12m return > 150%): kept off by the return guard
        stock("MOMEXT", 0.0040, "Fail")
        # Momentum-only with a decent trend but outside the top quintile
        stock("MOMSLOW", 0.0010, "Fail")
        # Momentum-only, ranked high but 60 weeks in Advance
        stock("MOMOLD", 0.0033, "Fail", tr=trend("MOMOLD", weeks=60))
        # Fillers that fill out the ranked universe
        for i, drift in enumerate((0.0005, 0.0004, 0.0003, 0.0002)):
            stock(f"FILL{i}", drift, "Fail", tr=trend(f"FILL{i}", stage="top", slope=-0.2))
        # Reversal: Quality base (B1) with no coverage by any signal job
        stock("NOCOV", 0.0002, "Pass", tr=trend("NOCOV", stage="base", slope=0.1, rs=-1.0))
        # Reversal: Quality decline with a Warren yellow_up inside the window (B3), and a monitored decline with an OLD signal
        stock("SIG", 0.0002, "Strong Pass", tr=trend("SIG", stage="decline", slope=-0.5, rs=-1.0))
        stock("SIGOLD", 0.0002, "Pass", tr=trend("SIGOLD", stage="decline", slope=-0.5, rs=-1.0))
        monitored += ["SIG", "SIGOLD"]
        # Stage split: a fresh Advance (8 weeks) with a recovering chart -> Reversal via B2; the same chart at 9 weeks is an established
        # uptrend -> Momentum with the deep-pullback tag; a fresh Advance with a shallow chart and a Top stage are on neither list
        stock("FRESH8", 0.0, "Pass", bars=recovering(), tr=trend("FRESH8", weeks=8))
        stock("FRESH9", 0.0, "Pass", bars=recovering(), tr=trend("FRESH9", weeks=9))
        stock("FRESHNO", 0.0002, "Pass", tr=trend("FRESHNO", weeks=4))
        stock("TOPQ", 0.0002, "Pass", tr=trend("TOPQ", stage="top", slope=0.2))
        stock("PEND", 0.0002, "Pass", tr=trend("PEND", stage="top", slope=0.2, weinstein_pending_direction="advance"))
        # Reversal: Momentum-only price structure (B2): 40% drawdown that has based and turned up
        stock("RECOV", 0.0, "Fail", bars=recovering(), tr=trend("RECOV", stage="base", slope=0.1, rs=-1.0))
        # Gate drops
        stock("SHORT", 0.0008, "Pass", bars=frame(0.0008, n=200))
        stock("STALE", 0.0008, "Pass", bars=frame(0.0008, end=AS_OF - timedelta(days=1)))
        stock("ILLIQ", 0.0008, "Pass", bars=frame(0.0008, volume=100.0))
        stock("DELIST", 0.0008, "Pass", sc=score("DELIST", "Pass", delisted_at=NOW))
        stock("NOBARS", 0.0008, "Pass", bars=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
        # An incomplete Overall verdict (None) is Momentum-only
        stock("INCOMP", 0.0014, "Fail", sc=score("INCOMP", None, overall=None, steps=None))
        s.add(WarrenSignalEvent(ticker="SIG", timeframe="2h", signal_kind="yellow_up", fired_at=datetime(2026, 10, 7, 12, 30), created_at=NOW))
        s.add(WarrenSignalEvent(ticker="SIGOLD", timeframe="2h", signal_kind="yellow_up", fired_at=datetime(2026, 9, 1, 12, 30), created_at=NOW))
        s.add(WarrenSignalEvent(ticker="MOM1", timeframe="2h", signal_kind="gray_up", fired_at=datetime(2026, 10, 7, 12, 30), created_at=NOW))

        # ETFs: an ordinary one in the top third, a leveraged one, SPY (excluded), and fillers to make a group of 6
        def etf(ticker, drift, name, tr=None):
            frames[ticker] = frame(drift)
            etfs.append(ticker)
            s.add(EtfScreenerRow(ticker=ticker, name=name))
            s.add(tr or trend(ticker))

        etf("ETFA", 0.0009, "Acme Growth ETF")
        etf("ETFB", 0.0003, "Acme Value ETF", tr=trend("ETFB", stage="decline", slope=-0.3))
        etf("ETFC", 0.0002, "Acme Bond ETF", tr=trend("ETFC", stage="decline", slope=-0.3))
        etf("ETFD", 0.0001, "Acme Gold ETF", tr=trend("ETFD", stage="decline", slope=-0.3))
        etf("ETFE", 0.0000, "Acme Oil ETF", tr=trend("ETFE", stage="decline", slope=-0.3))
        etf("ETFX", 0.0020, "Direxion Daily Widgets Bull 3X ETF")
        etf("ETFY", 0.0005, "Direxion Daily Gadgets Bull 3X ETF", tr=trend("ETFY", stage="decline", slope=-0.3))
        etf("SPY", 0.0006, "SPDR S&P 500 ETF")

        # market context
        s.add(MarketBreadthSnapshot(
            universe="sp500", as_of_date=AS_OF, computed_at=NOW, constituents=503, stale_excluded=0, sma50_eligible=500, sma50_above=175,
            pct_above_sma50=35.0, sma200_eligible=500, sma200_above=240, pct_above_sma200=48.0, hl_eligible=500, new_highs=30, new_lows=20,
            net_new_highs=10,
        ))
        s.add(MarketBreadthSnapshot(
            universe="sector:XLK", as_of_date=AS_OF, computed_at=NOW, constituents=85, stale_excluded=0, sma50_eligible=85, sma50_above=40,
            pct_above_sma50=47.0, sma200_eligible=85, sma200_above=60, pct_above_sma200=70.0, hl_eligible=85, new_highs=8, new_lows=1,
            net_new_highs=7,
        ))
        s.commit()

    monkeypatch.setattr(od, "load_tracked_universe", lambda session: sorted(stocks))
    monkeypatch.setattr(od, "load_etf_universe", lambda session: sorted(etfs))
    monkeypatch.setattr(od, "list_monitored_tickers", lambda session: (monitored, ["E1"]))
    monkeypatch.setattr(od, "read_cached_daily_bars_batch", lambda tickers, lookback_days, reference=None: {t: frames[t] for t in tickers if t in frames})
    return engine


def rows_of(run: od.ComputedRun, list_name: str) -> dict[str, dict]:
    return {r["ticker"]: r for r in run.rows if r["list_name"] == list_name}


# --- the lists -----------------------------------------------------------------------------------------------------------


def test_momentum_list_by_tier(world):
    run = od.compute_run(AS_OF, NOW)
    mom = rows_of(run, "momentum")
    assert mom["QUAL"]["tier"] == "quality" and mom["QUAL"]["rule_ids"] == [rules.RULE_A]
    assert mom["MOM1"]["tier"] == "momentum_only"
    assert mom["ETFA"]["tier"] == "etf"
    # extended (12m > 150%), outside the top quintile, too long in Advance, spy: all off the list
    for off in ("MOMEXT", "MOMSLOW", "MOMOLD", "SPY", "FILL0"):
        assert off not in mom, off


def test_the_ranked_universe_excludes_spy_and_every_gate_drop_and_ranks_etfs_apart(world):
    run = od.compute_run(AS_OF, NOW)
    ranked = run.summary["ranked_universe"]
    # stocks that pass the gate: QUAL MOM1 MOMEXT MOMSLOW MOMOLD FILL0-3 NOCOV SIG SIGOLD RECOV INCOMP FRESH8 FRESH9 FRESHNO TOPQ PEND = 19
    assert ranked == {"stocks": 19, "etfs": 5, "leveraged_etfs": 2}  # ETFA-ETFE ordinary (no SPY), ETFX/ETFY leveraged


def test_gate_drop_reasons_are_counted(world):
    run = od.compute_run(AS_OF, NOW)
    assert run.gate_drops == {"excluded": 1, "short_history": 1, "stale_bar": 1, "illiquid": 1, "delisted": 1, "no_bars": 1}
    assert run.summary["gate_passed"] == 19 + 5 + 2
    all_tickers = {r["ticker"] for r in run.rows}
    assert not all_tickers & {"SHORT", "STALE", "ILLIQ", "DELIST", "NOBARS", "SPY"}


def test_the_momentum_only_top_quintile_cut_is_computed_on_the_ranked_stocks(world):
    run = od.compute_run(AS_OF, NOW)
    cut = -(-19 // 5)  # ceil(19 / 5) = 4
    mom = rows_of(run, "momentum")
    for ticker, row in mom.items():
        if row["tier"] == "momentum_only":
            assert row["momentum_rank"] <= cut
    assert rows_of(run, "momentum")["MOM1"]["momentum_rank"] <= cut


def test_etfs_are_ranked_within_their_own_group_and_leveraged_apart(world):
    run = od.compute_run(AS_OF, NOW)
    mom = rows_of(run, "momentum")
    # ordinary group of 5: top third = rank <= 2, ETFA is rank 1. Leveraged group of 2: top third = rank 1 = ETFX
    assert mom["ETFA"]["momentum_rank"] == 1 and mom["ETFA"]["inputs"]["momentum_group"] == "etfs"
    assert mom["ETFX"]["momentum_rank"] == 1 and mom["ETFX"]["inputs"]["momentum_group"] == "leveraged_etfs"
    assert mom["ETFX"]["tags"]["leveraged"] == 3
    assert "ETFY" not in mom  # second of the leveraged group
    assert "leveraged" not in mom["ETFA"]["tags"]


def test_reversal_list_rules_and_not_covered(world):
    run = od.compute_run(AS_OF, NOW)
    rev = rows_of(run, "reversal")
    assert rules.RULE_B1 in rev["NOCOV"]["rule_ids"] and rev["NOCOV"]["tags"]["signal_status"] == rules.SIGNAL_NOT_COVERED
    assert rev["SIG"]["rule_ids"] == [rules.RULE_B3] and rev["SIG"]["tags"]["signal_status"] == rules.SIGNAL_FIRED
    assert "SIGOLD" not in rev  # monitored, but its only signal is outside the 10-session window -> no signal, not B3
    assert rev["RECOV"]["tier"] == "momentum_only" and rev["RECOV"]["rule_ids"] == [rules.RULE_B2]
    assert "signal_status" not in rev["RECOV"]["tags"]  # B3 is Quality only; the status is stored on Quality rows


def test_a_gray_up_is_not_a_b3_signal(world):
    # MOM1 has only a gray_up in the window (and is Momentum-only, advance): never on the Reversal list
    assert "MOM1" not in rows_of(od.compute_run(AS_OF, NOW), "reversal")


def test_signal_status_distinguishes_fired_no_signal_and_not_covered(world):
    with Session(od.engine) as s:
        status = od.load_signal_status(s, ["SIG", "SIGOLD", "NOCOV", "QUAL"], AS_OF)
    assert status == {"SIG": "fired", "SIGOLD": "no_signal", "NOCOV": "not_covered", "QUAL": "not_covered"}


def test_a_ticker_that_fired_but_left_the_monitored_lists_is_still_fired(world, monkeypatch):
    monkeypatch.setattr(od, "list_monitored_tickers", lambda session: ([], []))
    with Session(od.engine) as s:
        assert od.load_signal_status(s, ["SIG", "SIGOLD"], AS_OF) == {"SIG": "fired", "SIGOLD": "not_covered"}


def test_an_incomplete_overall_is_momentum_only_with_a_why_not_quality_tag(world):
    run = od.compute_run(AS_OF, NOW)
    row = rows_of(run, "momentum").get("INCOMP")
    assert row is not None and row["tier"] == "momentum_only"
    assert row["tags"]["why_not_quality"]["overall_verdict"] is None


def test_pass_with_caution_is_not_quality(world):
    with Session(od.engine) as s:
        s.merge(score("MOM1", "Pass with caution", overall=80))
        s.commit()
    row = rows_of(od.compute_run(AS_OF, NOW), "momentum")["MOM1"]
    assert row["tier"] == "momentum_only" and row["overall_verdict"] == "Pass with caution"
    assert row["tags"]["why_not_quality"]["overall_verdict"] == "Pass with caution"


# --- frozen inputs and tags ------------------------------------------------------------------------------------------------


def test_a_row_freezes_its_inputs_and_tags(world):
    row = rows_of(od.compute_run(AS_OF, NOW), "momentum")["MOM1"]
    assert row["overall_verdict"] == "Fail"  # the stored key, never the display word
    assert row["weinstein_stage"] == "advance" and row["vs_ma_pct"] == 8.0 and row["mansfield_rs"] == 3.0
    assert row["close"] > 0 and row["atr"] > 0 and row["adv_usd"] >= 25e6 and row["sector"] == "Technology"
    inputs = row["inputs"]
    assert inputs["company_name"] == "MOM1 Inc" and inputs["weeks_in_advance"] == 20
    assert inputs["step_scores"] == {"step1": 90, "step2": 90, "step4": 90, "step5": 90}
    assert inputs["return_3m"] is not None and inputs["return_12m"] is not None and inputs["momentum_group"] == "stocks"
    tags = row["tags"]
    assert tags["why_not_quality"] == {"overall_verdict": "Fail", "failed_steps": [], "incomplete_steps": [], "moat": "wide_moat"}
    assert tags["held_back_by_moat"] is True  # steps 80 >= 70, overall 55 < 70
    assert tags["market"] == {"as_of_date": "2026-10-09", "pct_above_sma50": 35.0, "pct_above_sma200": 48.0, "net_new_highs": 10}
    assert tags["sector"]["etf"] == "XLK" and tags["sector"]["breadth"]["pct_above_sma50"] == 47.0


def test_no_ticker_is_ever_on_both_lists(world):
    run = od.compute_run(AS_OF, NOW)
    tickers = [r["ticker"] for r in run.rows]
    assert len(tickers) == len(set(tickers)), sorted(t for t in set(tickers) if tickers.count(t) > 1)
    assert not set(rows_of(run, "momentum")) & set(rows_of(run, "reversal"))
    assert all("also_on" not in r["tags"] for r in run.rows)


def test_trend_stage_decides_the_list(world):
    run = od.compute_run(AS_OF, NOW)
    mom, rev = rows_of(run, "momentum"), rows_of(run, "reversal")
    assert "FRESH8" in rev and rev["FRESH8"]["rule_ids"] == [rules.RULE_B2] and "FRESH8" not in mom  # 8 weeks = fresh
    assert "FRESH9" in mom and "FRESH9" not in rev  # 9 weeks = established
    assert mom["FRESH9"]["tags"]["deep_pullback"] is True and rev["FRESH8"]["tags"].get("deep_pullback") is None
    assert "deep_pullback" not in mom["QUAL"]["tags"]
    for neither in ("FRESHNO", "TOPQ"):
        assert neither not in mom and neither not in rev, neither
    assert rev["PEND"]["rule_ids"] == [rules.RULE_B1] and "PEND" not in mom  # Top with a pending Advance
    assert run.summary["deep_pullback"] == 1
    assert run.summary["stage_split"]["neither"] >= 2


def test_an_established_advance_with_a_deep_drawdown_is_momentum_not_reversal(world):
    run = od.compute_run(AS_OF, NOW)
    assert "FRESH9" not in rows_of(run, "reversal") and "FRESH9" in rows_of(run, "momentum")


def test_list_order_is_one_based_and_momentum_is_sorted_by_composite(world):
    run = od.compute_run(AS_OF, NOW)
    mom = [r for r in run.rows if r["list_name"] == "momentum"]
    assert [r["list_order"] for r in mom] == list(range(1, len(mom) + 1))
    composites = [r["composite"] for r in mom]
    assert composites == sorted(composites, reverse=True)


def test_the_summary_counts_per_list_tier_and_rule(world):
    summary = od.compute_run(AS_OF, NOW).summary
    assert summary["counts"]["momentum"]["quality"][rules.RULE_A] == 2  # QUAL and FRESH9
    assert summary["counts"]["reversal"]["momentum_only"][rules.RULE_B2] == 1
    assert summary["list_totals"]["momentum"] == sum(t["total"] for t in summary["counts"]["momentum"].values())
    assert summary["quality_not_covered"] >= 1 and summary["rs_benchmark"] is None
    assert summary["market"]["breadth"]["net_new_highs"] == 10


# --- gate edge cases through the real pipeline ----------------------------------------------------------------------------


def test_a_provisional_as_of_bar_is_dropped(world):
    with Session(od.engine) as s:
        # QUAL's as-of bar was written at 10:00 ET on the session itself, before the close
        s.add(SharedBarsCache(ticker="QUAL", interval="1d", bar_time=datetime(2026, 10, 9), open=1, high=1, low=1, close=1, volume=1, fetched_at=datetime(2026, 10, 9, 14, 0)))
        s.commit()
    run = od.compute_run(AS_OF, NOW)
    assert run.gate_drops["provisional_bar"] == 1 and "QUAL" not in {r["ticker"] for r in run.rows}


def test_a_run_refuses_to_freeze_a_hollow_list_when_stage_rows_are_stale(world):
    with Session(od.engine) as s:
        for row in s.exec(select(TrendAnalysis)).all():
            row.bars_as_of = AS_OF - timedelta(days=7)
            s.add(row)
        s.commit()
    with pytest.raises(od.OpportunityRunRefused):
        od.compute_run(AS_OF, NOW)


def test_a_stale_stage_row_removes_stage_rules_but_not_the_ticker(world):
    with Session(od.engine) as s:
        row = s.get(TrendAnalysis, "QUAL")
        row.bars_as_of = AS_OF - timedelta(days=1)
        s.add(row)
        s.commit()
    run = od.compute_run(AS_OF, NOW)
    assert run.summary["stale_stage_rows"] == 1
    assert "QUAL" not in rows_of(run, "momentum")  # no fresh stage -> rule A cannot be judged


def test_stale_score_rows_are_counted_not_hidden(world):
    with Session(od.engine) as s:
        row = s.get(TickerScore, "QUAL")
        row.formula_version = 5
        s.add(row)
        s.commit()
    assert od.compute_run(AS_OF, NOW).summary["stale_score_rows"] == 1


# --- persistence -------------------------------------------------------------------------------------------------------------


def test_persist_creates_a_run_with_its_rows_and_hash(world):
    run = od.compute_run(AS_OF, NOW)
    result = od.persist_run(run, now=NOW)
    assert result["status"] == "created" and result["rows"] == len(run.rows)
    with Session(world) as s:
        stored = s.exec(select(OpportunityRun)).one()
        assert (stored.kind, stored.as_of_date, stored.last_bar_date) == ("weekly", AS_OF, AS_OF)
        assert stored.rules_hash == rules.rules_hash() and stored.rules_version == rules.RULES_VERSION
        assert stored.score_formula_version == 6 and stored.universe_size == 24 + 8  # 24 stocks, 8 ETFs (SPY included)
        rows = s.exec(select(OpportunitySnapshotRow).where(OpportunitySnapshotRow.run_id == stored.id)).all()
        assert len(rows) == len(run.rows)
        assert json.loads(next(r for r in rows if r.ticker == "MOM1").rule_ids_json) == [rules.RULE_A]


def test_a_rerun_for_the_same_date_is_a_no_op(world):
    run = od.compute_run(AS_OF, NOW)
    first = od.persist_run(run, now=NOW)
    again = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW + timedelta(hours=1))
    assert again["status"] == "exists" and again["run_id"] == first["run_id"]
    with Session(world) as s:
        assert len(s.exec(select(OpportunityRun)).all()) == 1
        assert s.exec(select(OpportunityRun)).one().created_at == NOW
        assert len(s.exec(select(OpportunitySnapshotRow)).all()) == len(run.rows)
    assert od.existing_run_id(AS_OF) == first["run_id"]
    assert od.existing_run_id(AS_OF - timedelta(days=7)) is None


def test_force_replaces_the_run_and_its_rows(world):
    first = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    with Session(world) as s:  # tamper with the stored rows so a replace is visible
        s.exec(select(OpportunitySnapshotRow)).first().overall_score = -1
        s.commit()
    result = od.persist_run(od.compute_run(AS_OF, NOW), force=True, now=NOW + timedelta(days=1))
    assert result["status"] == "replaced" and result["replaced_run_id"] == first["run_id"]
    with Session(world) as s:
        (stored,) = s.exec(select(OpportunityRun)).all()
        assert stored.id == result["run_id"] and stored.created_at == NOW + timedelta(days=1)
        rows = s.exec(select(OpportunitySnapshotRow)).all()
        assert len(rows) == first["rows"] and {r.run_id for r in rows} == {stored.id}  # no orphan rows of the old run
        assert all(r.overall_score != -1 for r in rows)


def test_a_failed_force_leaves_the_old_run_untouched(world):
    first = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    bad = od.compute_run(AS_OF, NOW)
    bad.rows[3]["ticker"] = None  # NOT NULL: the insert fails after the delete
    with pytest.raises(IntegrityError):
        od.persist_run(bad, force=True, now=NOW + timedelta(days=1))
    with Session(world) as s:
        assert [r.id for r in s.exec(select(OpportunityRun)).all()] == [first["run_id"]]
        assert len(s.exec(select(OpportunitySnapshotRow)).all()) == first["rows"]


def test_runs_for_different_dates_coexist_and_are_never_modified(world):
    first = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    with Session(world) as s:
        before = [(r.id, r.ticker, r.overall_score, r.inputs_json) for r in s.exec(select(OpportunitySnapshotRow)).all()]
    # an earlier as-of date: every stage row is "stale" for it, so the run refuses; build it from a copy of the first run instead
    other = od.compute_run(AS_OF, NOW)
    other.as_of = date(2026, 10, 2)
    second = od.persist_run(other, now=NOW)
    assert second["status"] == "created" and second["run_id"] != first["run_id"]
    with Session(world) as s:
        after = [(r.id, r.ticker, r.overall_score, r.inputs_json) for r in s.exec(select(OpportunitySnapshotRow)).all() if r.run_id == first["run_id"]]
    assert sorted(after) == sorted(before)


def test_the_database_rejects_a_duplicate_run_or_row(world):
    od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    with Session(world) as s:
        s.add(OpportunityRun(kind="weekly", as_of_date=AS_OF, last_bar_date=AS_OF, universe_size=1, rules_hash="x", rules_version="1", score_formula_version=6, created_at=NOW))
        with pytest.raises(IntegrityError):
            s.commit()
    with Session(world) as s:
        row = s.exec(select(OpportunitySnapshotRow)).first()
        s.add(OpportunitySnapshotRow(run_id=row.run_id, list_name=row.list_name, ticker=row.ticker, tier="etf", list_order=99, rule_ids_json="[]"))
        with pytest.raises(IntegrityError):
            s.commit()
    with Session(world) as s:  # unique across BOTH lists: the other list's name does not make the same ticker a new row
        row = s.exec(select(OpportunitySnapshotRow)).first()
        other = "reversal" if row.list_name == "momentum" else "momentum"
        s.add(OpportunitySnapshotRow(run_id=row.run_id, list_name=other, ticker=row.ticker, tier="etf", list_order=99, rule_ids_json="[]"))
        with pytest.raises(IntegrityError):
            s.commit()


# --- the pool and the --force cascade ------------------------------------------------------------------------------------------


def test_the_pool_is_exactly_the_gate_passing_set(world):
    run = od.compute_run(AS_OF, NOW)
    gate_drops = run.summary["gate_drops"]
    passed = run.summary["gate_passed"]
    assert len(run.pool) == passed == run.summary["pool_rows"]
    pooled = {p["ticker"] for p in run.pool}
    assert len(pooled) == len(run.pool)  # one row per ticker
    # every gate drop (and SPY) is out of the pool; every listed ticker is in it
    assert not pooled & {"SHORT", "STALE", "ILLIQ", "DELIST", "NOBARS", "SPY"}
    assert {r["ticker"] for r in run.rows} <= pooled
    assert passed + sum(gate_drops.values()) == run.universe_size


def test_a_pool_row_says_what_the_stage_allowed_and_whether_it_was_listed(world):
    run = od.compute_run(AS_OF, NOW)
    pool = {p["ticker"]: p for p in run.pool}
    listed = {r["ticker"]: r["list_name"] for r in run.rows}
    for t, p in pool.items():
        assert p["listed"] == (t in listed) and p["list_name"] == listed.get(t)
        assert p["list_name"] in (None, p["assigned_list"])  # a ticker is only ever listed on the list its stage allows
    assert pool["TOPQ"]["assigned_list"] is None and pool["TOPQ"]["listed"] is False  # Top: allowed on neither
    assert pool["MOMSLOW"]["assigned_list"] == "momentum" and pool["MOMSLOW"]["listed"] is False  # allowed, rule A not hit
    assert pool["MOM1"]["assigned_list"] == "momentum" and pool["MOM1"]["listed"] is True
    assert pool["MOM1"]["overall_verdict"] == "Fail"  # the raw stored word, never relabelled
    assert pool["MOM1"]["weinstein_stage"] == "advance" and pool["MOM1"]["close"] is not None and pool["MOM1"]["adv_usd"] is not None


def test_persist_writes_the_pool_in_the_same_transaction_as_the_run(world):
    run = od.compute_run(AS_OF, NOW)
    result = od.persist_run(run, now=NOW)
    assert result["pool_rows"] == len(run.pool)
    with Session(world) as s:
        stored = s.exec(select(OpportunityRun)).one()
        pool = s.exec(select(OpportunityPoolRow).where(OpportunityPoolRow.run_id == stored.id)).all()
        assert {p.ticker for p in pool} == {p["ticker"] for p in run.pool}
        assert {p.ticker for p in pool if p.listed} == {r["ticker"] for r in run.rows}
        assert json.loads(next(p for p in pool if p.ticker == "MOM1").inputs_json)["momentum_group"] == "stocks"


def test_a_failed_pool_insert_rolls_the_whole_run_back(world):
    run = od.compute_run(AS_OF, NOW)
    run.pool[0]["tier"] = None  # NOT NULL: fails after the run and the snapshot rows were added
    with pytest.raises(IntegrityError):
        od.persist_run(run, now=NOW)
    with Session(world) as s:
        assert s.exec(select(OpportunityRun)).all() == [] and s.exec(select(OpportunitySnapshotRow)).all() == []
        assert s.exec(select(OpportunityPoolRow)).all() == []


def test_the_database_rejects_a_duplicate_pool_row(world):
    od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    with Session(world) as s:
        row = s.exec(select(OpportunityPoolRow)).first()
        s.add(OpportunityPoolRow(run_id=row.run_id, ticker=row.ticker, tier="etf"))
        with pytest.raises(IntegrityError):
            s.commit()


def _seed_children(engine, run_id: int, other_run_id: int) -> None:
    with Session(engine) as s:
        for rid in (run_id, other_run_id):
            s.add(OpportunityOutcome(run_id=rid, ticker="MOM1", horizon=5, status="pending", rules_version="2", computed_at=NOW))
        s.add(OpportunityPick(as_of_date=AS_OF, ticker="MOM1", picked_at=NOW, source="opportunities_page"))
        s.add(OpportunityPick(as_of_date=date(2026, 10, 2), ticker="MOM1", picked_at=NOW, source="opportunities_page"))
        s.commit()


def test_force_deletes_the_pool_and_outcome_rows_of_that_run_only_and_never_a_pick(world):
    first = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    other = od.compute_run(AS_OF, NOW)
    other.as_of = date(2026, 10, 2)
    second = od.persist_run(other, now=NOW)
    _seed_children(world, first["run_id"], second["run_id"])
    result = od.persist_run(od.compute_run(AS_OF, NOW), force=True, now=NOW + timedelta(days=1))
    assert result["status"] == "replaced"
    assert result["deleted"]["outcome_rows"] == 1 and "pick_rows" not in result["deleted"]
    assert result["deleted"]["pool_rows"] == first["pool_rows"] and result["deleted"]["snapshot_rows"] == first["rows"]
    with Session(world) as s:
        new_id = result["run_id"]
        rows = s.exec(select(OpportunityOutcome)).all()
        assert [r.run_id for r in rows] == [second["run_id"]]  # the other run's outcomes survive; none left for the replaced run
        pool_runs = {p.run_id for p in s.exec(select(OpportunityPoolRow)).all()}
        assert pool_runs == {new_id, second["run_id"]}  # the replaced run's old pool is gone, the new one is in
        assert len(s.exec(select(OpportunityPoolRow).where(OpportunityPoolRow.run_id == new_id)).all()) == first["pool_rows"]
        # both picks (the rebuilt date and the other date) are exactly as they were
        assert sorted((p.as_of_date, p.ticker, p.picked_at) for p in s.exec(select(OpportunityPick)).all()) == [
            (date(2026, 10, 2), "MOM1", NOW), (AS_OF, "MOM1", NOW),
        ]


def test_a_pick_survives_force_even_when_the_rebuilt_run_gets_the_same_id(world):
    first = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    with Session(world) as s:
        s.add(OpportunityPick(as_of_date=AS_OF, ticker="MOM1", picked_at=NOW, source="opportunities_page"))
        s.commit()
    again = od.persist_run(od.compute_run(AS_OF, NOW), force=True, now=NOW + timedelta(days=1))
    assert again["run_id"] == first["run_id"]  # sqlite reuses the highest id: a run-id key would have re-attached the pick silently
    with Session(world) as s:
        (pick,) = s.exec(select(OpportunityPick)).all()
        assert (pick.as_of_date, pick.ticker, pick.picked_at) == (AS_OF, "MOM1", NOW)


def test_a_failed_force_keeps_the_pool_outcomes_and_picks(world):
    first = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    _seed_children(world, first["run_id"], first["run_id"] + 100)
    bad = od.compute_run(AS_OF, NOW)
    bad.pool[2]["tier"] = None
    with pytest.raises(IntegrityError):
        od.persist_run(bad, force=True, now=NOW + timedelta(days=1))
    with Session(world) as s:
        assert len(s.exec(select(OpportunityPoolRow).where(OpportunityPoolRow.run_id == first["run_id"])).all()) == first["pool_rows"]
        assert len(s.exec(select(OpportunityOutcome)).all()) == 2 and len(s.exec(select(OpportunityPick)).all()) == 2


def test_a_rerun_without_force_computes_and_writes_nothing_new(world):
    first = od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    od.persist_run(od.compute_run(AS_OF, NOW), now=NOW + timedelta(hours=1))
    with Session(world) as s:
        assert len(s.exec(select(OpportunityPoolRow)).all()) == first["pool_rows"]


# --- reading -------------------------------------------------------------------------------------------------------------------


def test_get_run_and_dates(world):
    assert od.get_run() is None and od.list_run_dates() == []
    od.persist_run(od.compute_run(AS_OF, NOW), now=NOW)
    out = od.get_run()
    assert out.as_of_date == AS_OF and out.rule_labels[rules.RULE_B2] == "Price structure"
    assert [r.list_order for r in out.momentum] == list(range(1, len(out.momentum) + 1))
    assert od.get_run(AS_OF).id == out.id and od.get_run(date(2026, 1, 2)) is None
    (entry,) = od.list_run_dates()
    assert (entry.as_of_date, entry.momentum_count, entry.reversal_count) == (AS_OF, len(out.momentum), len(out.reversal))
