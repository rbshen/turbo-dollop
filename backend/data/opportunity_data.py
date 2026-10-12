"""Orchestration of the weekly opportunity agent: load stored data, evaluate scoring/opportunity_rules.py, persist an
OpportunityRun with its OpportunitySnapshotRow rows, and read them back for the API. Spec: docs/specs/opportunities.md.

STORED DATA ONLY: this module makes no FMP call and writes nothing but the two new tables. Inputs: the tracked stock universe and
the ETF universe (data/tracked_universe.py), the shared daily-bars cache (read in chunks of CHUNK_SIZE tickers, so memory stays
flat), TickerScore (verdicts, scores, moat), TrendAnalysis (the Weinstein stage row), the momentum ranking
(scoring/momentum.py::compute_momentum_ranking over the cached closes), the monitored-watchlist Warren / BB+RSI event tables and
the latest MarketBreadthSnapshot rows.

The ranked universe (state it wherever a rank is shown): every ticker that PASSES THE GATE, ranked within its own group -- the
tracked stocks, the ordinary ETFs and the leveraged ETFs separately. SPY is excluded, so it is in no ranking.

`engine` is a module-level reference so tests can monkeypatch it (the per-module convention)."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
from sqlalchemy import delete, func
from sqlmodel import Session, select

from clients.shared_bars_cache import (
    _CLOSE_SETTLE,
    _EASTERN,
    _MARKET_CLOSE_HOUR_ET,
    _most_recent_completed_trading_date,
    read_cached_daily_bars_batch,
)
from core.db import engine
from core.models import (
    EtfScreenerRow,
    FundamentalsCache,
    MarketBreadthSnapshot,
    OpportunityOutcome,
    OpportunityPick,
    OpportunityPoolOutcome,
    OpportunityPoolRow,
    OpportunityRun,
    OpportunitySnapshotRow,
    ScoreWeightSettings,
    SharedBarsCache,
    TechnicalEntrySignalEvent,
    TickerScore,
    TrendAnalysis,
    WarrenSignalEvent,
)
from core.schemas import OpportunityDateOut, OpportunityRowOut, OpportunityRunOut
from data.market_breadth_data import SECTOR_TO_ETF, UNIVERSE as BREADTH_UNIVERSE, sector_universe
from data.sector_heatmap_data import SECTOR_ETFS
from data.tracked_universe import load_etf_universe, load_tracked_universe, read_rs_benchmark
from data.watchlists import list_monitored_tickers
from helpers.first import _first
from scoring import opportunity_rules as rules
from scoring.momentum import compute_momentum_ranking
from scoring.overall import SCORE_FORMULA_VERSION

logger = logging.getLogger(__name__)

KIND_WEEKLY = "weekly"
CHUNK_SIZE = 60  # tickers of bars held in memory at a time (the server has ~1 GB)
FETCH_LOOKBACK_DAYS = 800  # 12 months of ranking history + the weekly-EMA warm-up, with slack
# A run refuses to freeze a hollow list: when fewer than this share of the gate-passing tickers have a Weinstein row computed from
# the run's own last bar, the nightly stage job did not finish and the lists would silently omit every stage-dependent name.
MIN_FRESH_STAGE_SHARE = 0.90

GROUP_STOCKS = "stocks"
GROUP_ETFS = "etfs"
GROUP_LEVERAGED = "leveraged_etfs"


class OpportunityRunRefused(RuntimeError):
    """The inputs are too stale or too thin to freeze a list; nothing was written."""


@dataclass
class ComputedRun:
    as_of: date
    last_bar_date: date
    universe_size: int
    score_formula_version: int
    weights_version: int | None
    summary: dict
    rows: list[dict]  # one dict per OpportunitySnapshotRow (without run_id)
    pool: list[dict] = field(default_factory=list)  # one dict per OpportunityPoolRow: EVERY gate-passing ticker, listed or not
    gate_drops: dict[str, int] = field(default_factory=dict)


def latest_completed_session(reference: datetime | None = None) -> date:
    """The last completed XNYS session (holiday- and early-close-aware): the as-of date of a run started now."""
    return _most_recent_completed_trading_date(reference)


# --- loading -------------------------------------------------------------------------------------------------------------


def _signal_window_start(as_of: date) -> date:
    """The first of the last B3_SIGNAL_WINDOW_SESSIONS XNYS sessions ending at `as_of` (falls back to calendar days)."""
    try:
        from helpers.trading_calendar import xnys_sessions

        days = [d for d, _o, _c in xnys_sessions(as_of - timedelta(days=30), as_of)]
        if len(days) >= rules.B3_SIGNAL_WINDOW_SESSIONS:
            return days[-rules.B3_SIGNAL_WINDOW_SESSIONS]
    except Exception:  # noqa: BLE001 -- a calendar problem must not stop the run
        logger.warning("Opportunity run: XNYS calendar unavailable, using a 14-calendar-day signal window.")
    return as_of - timedelta(days=14)


def load_signal_status(session: Session, tickers: list[str], as_of: date) -> dict[str, str]:
    """{ticker: fired | no_signal | not_covered} for B3.

    `fired`: a Warren blue_up / yellow_up or a BB+RSI event dated in the last 10 sessions -- a fact in the event tables, true
    whether or not the ticker is still monitored. Otherwise `no_signal` when the ticker is on a monitored watchlist right now
    (the only tickers the Warren, BB+RSI and Liquidity Zone jobs run for), so a signal COULD have fired and did not. Any other
    ticker is `not_covered`: the signal jobs do not run for it, so "no signal" would be a claim nobody checked."""
    monitored = set(list_monitored_tickers(session)[0])
    start = datetime.combine(_signal_window_start(as_of), time.min)
    end = datetime.combine(as_of + timedelta(days=1), time.min)
    fired = set(
        session.exec(
            select(WarrenSignalEvent.ticker).where(
                WarrenSignalEvent.signal_kind.in_(rules.B3_WARREN_KINDS), WarrenSignalEvent.fired_at >= start, WarrenSignalEvent.fired_at < end
            )
        ).all()
    ) | set(
        session.exec(
            select(TechnicalEntrySignalEvent.ticker).where(
                TechnicalEntrySignalEvent.signal_type == "bb_rsi", TechnicalEntrySignalEvent.fired_at >= start, TechnicalEntrySignalEvent.fired_at < end
            )
        ).all()
    )
    status: dict[str, str] = {}
    for ticker in tickers:
        if ticker in fired:
            status[ticker] = rules.SIGNAL_FIRED
        elif ticker in monitored:
            status[ticker] = rules.SIGNAL_NONE
        else:
            status[ticker] = rules.SIGNAL_NOT_COVERED
    return status


def _provisional_as_of_bars(session: Session, tickers: list[str], as_of: date) -> set[str]:
    """Tickers whose as-of bar was written before that session's close (a live, partial bar): the same test the bars cache uses
    (`_provisional_last_bar_tickers`), applied to the as-of row itself."""
    if not tickers:
        return set()
    close = datetime.combine(as_of, time(_MARKET_CLOSE_HOUR_ET), tzinfo=_EASTERN) + _CLOSE_SETTLE
    rows = session.exec(
        select(SharedBarsCache.ticker, SharedBarsCache.fetched_at).where(
            SharedBarsCache.interval == "1d", SharedBarsCache.ticker.in_(tickers), SharedBarsCache.bar_time == datetime.combine(as_of, time.min)
        )
    ).all()
    return {ticker for ticker, fetched_at in rows if fetched_at.astimezone(_EASTERN) < close}


def _latest_breadth(session: Session, universe: str, as_of: date) -> dict | None:
    row = session.exec(
        select(MarketBreadthSnapshot)
        .where(MarketBreadthSnapshot.universe == universe, MarketBreadthSnapshot.as_of_date <= as_of)
        .order_by(MarketBreadthSnapshot.as_of_date.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return {
        "as_of_date": row.as_of_date.isoformat(),
        "pct_above_sma50": row.pct_above_sma50,
        "pct_above_sma200": row.pct_above_sma200,
        "net_new_highs": row.net_new_highs,
    }


def _exchanges(session: Session, tickers: list[str]) -> dict[str, str | None]:
    """The cached profile's exchange per ticker (the TradingView export needs EXCHANGE:SYMBOL). Cache-only."""
    out: dict[str, str | None] = {}
    for i in range(0, len(tickers), 300):
        chunk = tickers[i : i + 300]
        rows = session.exec(
            select(FundamentalsCache.ticker, FundamentalsCache.raw_json).where(
                FundamentalsCache.ticker.in_(chunk), FundamentalsCache.statement_type == "profile", FundamentalsCache.period == "latest"
            )
        ).all()
        for ticker, raw in rows:
            try:
                profile = _first(json.loads(raw)) or {}
            except (TypeError, ValueError):
                profile = {}
            out[ticker] = profile.get("exchangeShortName") or profile.get("exchange")
    return out


def _weeks_in_advance(trend: TrendAnalysis, as_of: date) -> int | None:
    if trend.weinstein_stage != "advance" or trend.weinstein_stage_since_date is None:
        return None
    return round((as_of - trend.weinstein_stage_since_date).days / 7)


def _rank_group(closes: dict[str, pd.DataFrame], as_of: date) -> dict[str, dict]:
    ranked = compute_momentum_ranking(closes, pd.Timestamp(as_of))
    return {
        r.ticker: {
            "rank": r.rank,
            "group_size": len(ranked),
            "return_3m": r.return_3mo,
            "return_12m": r.return_12mo,
            "composite": r.composite_score,
        }
        for r in ranked
    }


# --- the run ---------------------------------------------------------------------------------------------------------------


def _sorted_momentum(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-(r["composite"] if r["composite"] is not None else float("-inf")), r["ticker"]))


def _sorted_reversal(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda r: (-len(r["rule_ids"]), -(r["composite"] if r["composite"] is not None else float("-inf")), r["ticker"]),
    )


def compute_run(as_of: date | None = None, now: datetime | None = None) -> ComputedRun:
    """Evaluates every rule over the universe as of `as_of` (default: the last completed session) and returns the run WITHOUT
    writing it. Reads only. Raises OpportunityRunRefused when the stage rows are too stale to freeze a list."""
    now = now or datetime.now(timezone.utc)
    as_of = as_of or latest_completed_session(now)

    with Session(engine) as session:
        stocks = [t for t in load_tracked_universe(session)]
        etfs = [t for t in load_etf_universe(session)]
        universe = sorted(set(stocks) | set(etfs))
        etf_set = set(etfs)
        scores = {r.ticker: r for r in session.exec(select(TickerScore).where(TickerScore.ticker.in_(universe))).all()}
        trends = {r.ticker: r for r in session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker.in_(universe))).all()}
        etf_names = {r.ticker: r.name for r in session.exec(select(EtfScreenerRow).where(EtfScreenerRow.ticker.in_(etfs))).all()}
        weights_row = session.get(ScoreWeightSettings, "default")
        weights_version = weights_row.weights_version if weights_row is not None else None
        rs_benchmark = read_rs_benchmark(session)
        signal_status = load_signal_status(session, universe, as_of)
        market = _latest_breadth(session, BREADTH_UNIVERSE, as_of)
        sector_breadth = {etf: _latest_breadth(session, sector_universe(etf), as_of) for etf, _ in SECTOR_ETFS}

    # --- pass 1: bars in chunks -> price features; keep only the closes of gate-passing tickers for the ranking
    features: dict[str, rules.Features] = {}
    closes: dict[str, pd.DataFrame] = {}
    stale_stage = 0
    stale_scores = 0
    for i in range(0, len(universe), CHUNK_SIZE):
        chunk = universe[i : i + CHUNK_SIZE]
        frames = read_cached_daily_bars_batch(chunk, FETCH_LOOKBACK_DAYS, now)
        with Session(engine) as session:
            provisional = _provisional_as_of_bars(session, chunk, as_of)
        for ticker in chunk:
            score, trend = scores.get(ticker), trends.get(ticker)
            is_etf = ticker in etf_set
            frame = frames.get(ticker)
            price = rules.compute_price_features(frame, as_of) if frame is not None and not frame.empty else None
            f = rules.Features(
                ticker=ticker,
                is_etf=is_etf,
                leverage=rules.leverage_factor(ticker, etf_names.get(ticker) or (score.company_name if score else None)) if is_etf else None,
                delisted=bool(score is not None and score.delisted_at is not None),
                price=price,
                provisional_last_bar=ticker in provisional,
                signal_status=signal_status.get(ticker, rules.SIGNAL_NOT_COVERED),
            )
            if score is not None and not is_etf:
                f.overall_verdict, f.overall_score, f.steps_score = score.overall_verdict, score.overall_score, score.steps_score
                f.moat, f.moat_multiplier = score.moat, score.moat_multiplier
                f.step_scores = {k: getattr(score, f"{k}_score") for k in rules.STEP_LABELS}
                f.step_verdicts = {k: getattr(score, f"{k}_verdict") for k in rules.STEP_LABELS}
                if score.formula_version != SCORE_FORMULA_VERSION or (weights_version is not None and score.weights_version != weights_version):
                    stale_scores += 1
            if trend is not None and trend.bars_as_of == as_of:
                f.stage, f.pending_direction = trend.weinstein_stage, trend.weinstein_pending_direction
                f.weeks_in_advance = _weeks_in_advance(trend, as_of)
                f.ma_slope_pct, f.vs_ma_pct, f.mansfield_rs = trend.weinstein_ma_slope_pct, trend.weinstein_vs_ma_pct, trend.weinstein_mansfield_rs
            features[ticker] = f
            if rules.gate_reason(f, as_of) is None and frame is not None:
                closes[ticker] = frame.loc[frame.index <= pd.Timestamp(as_of), ["close"]]
        del frames

    gate = {t: rules.gate_reason(f, as_of) for t, f in features.items()}
    passed = [t for t, reason in gate.items() if reason is None]
    gate_drops: dict[str, int] = {}
    for reason in gate.values():
        if reason is not None:
            gate_drops[reason] = gate_drops.get(reason, 0) + 1
    for t in passed:
        if trends.get(t) is None or trends[t].bars_as_of != as_of:
            stale_stage += 1
    if passed and (len(passed) - stale_stage) / len(passed) < MIN_FRESH_STAGE_SHARE:
        raise OpportunityRunRefused(
            f"only {len(passed) - stale_stage} of {len(passed)} gate-passing tickers have a Weinstein row as of {as_of} "
            f"(need {MIN_FRESH_STAGE_SHARE:.0%}); the nightly stage job has not caught up. Nothing written."
        )

    # --- rank within each group (the gate-passing tickers only; SPY and delisted never reach here)
    groups = {GROUP_STOCKS: {}, GROUP_ETFS: {}, GROUP_LEVERAGED: {}}
    for t in passed:
        f = features[t]
        groups[GROUP_LEVERAGED if f.is_etf and f.leverage else GROUP_ETFS if f.is_etf else GROUP_STOCKS][t] = closes[t]
    group_of: dict[str, str] = {}
    rank_info: dict[str, dict] = {}
    for name, members in groups.items():
        for t in members:
            group_of[t] = name
        rank_info.update(_rank_group(members, as_of))
    ranked_sizes = {name: sum(1 for t in members if t in rank_info) for name, members in groups.items()}
    for t, info in rank_info.items():
        f = features[t]
        f.momentum_rank, f.momentum_group_size = info["rank"], info["group_size"]
        f.return_3m, f.return_12m = info["return_3m"], info["return_12m"]
    del closes

    # --- sector context (the 11 SPDR ETFs' own stage and momentum)
    sector_etf = {}
    for etf, _name in SECTOR_ETFS:
        f = features.get(etf)
        trend = trends.get(etf)
        fresh = trend is not None and trend.bars_as_of == as_of
        sector_etf[etf] = {
            "etf": etf,
            "stage": trend.weinstein_stage if fresh else None,
            "vs_ma_pct": trend.weinstein_vs_ma_pct if fresh else None,
            "momentum_rank": f.momentum_rank if f else None,
            "momentum_group_size": f.momentum_group_size if f else None,
            "breadth": sector_breadth.get(etf),
        }
    market_context = {
        "breadth": market,
        "sectors_in_advance": sum(1 for s in sector_etf.values() if s["stage"] == "advance"),
        "sector_etfs": sector_etf,
    }

    # --- evaluate the rules
    tiers = {t: rules.tier_for(features[t]) for t in passed}
    # One placement per ticker: trend stage decides the list (scoring/opportunity_rules.py::assign_list), so the lists cannot overlap.
    placements = {t: rules.place(features[t], tiers[t]) for t in passed}
    listed = {t: p for t, p in placements.items() if p.list_name is not None}
    exchanges = _exchanges_for(sorted(listed))

    def build_row(t: str, list_name: str, rule_ids: list[str], deep_pullback: bool) -> dict:
        f, tier = features[t], tiers[t]
        p = f.price
        score, trend = scores.get(t), trends.get(t)
        sector_name = score.sector if score is not None and not f.is_etf else None
        sector_key = SECTOR_TO_ETF.get(sector_name or "")
        sector_tag = (
            {"name": sector_name, **{k: v for k, v in sector_etf[sector_key].items() if k != "etf"}, "etf": sector_key}
            if sector_key
            else None
        )
        info = rank_info.get(t, {})
        inputs = {
            "company_name": (score.company_name if score is not None else None) or etf_names.get(t),
            "is_etf": f.is_etf,
            "exchange": exchanges.get(t),
            "step_scores": f.step_scores,
            "step_verdicts": f.step_verdicts,
            "moat": f.moat,
            "moat_multiplier": f.moat_multiplier,
            "pending_direction": f.pending_direction,
            "weeks_in_advance": f.weeks_in_advance,
            "stage_since": trend.weinstein_stage_since_date.isoformat() if trend is not None and trend.weinstein_stage_since_date else None,
            "stage_since_is_lower_bound": trend.weinstein_stage_since_is_lower_bound if trend is not None else None,
            "return_3m": f.return_3m,
            "return_12m": f.return_12m,
            "composite": info.get("composite"),
            "momentum_group": group_of.get(t),
            "momentum_group_size": f.momentum_group_size,
            "drawdown_pct": p.drawdown_pct if p else None,
            "higher_low": p.higher_low if p else None,
            "above_10w_sma": p.above_10w_sma if p else None,
            "ma_slope_now": p.ma_slope_now if p else None,
            "ma_slope_4w_ago": p.ma_slope_4w_ago if p else None,
            "signal_status": f.signal_status,
            "first_bar_date": p.first_bar_date.isoformat() if p else None,
            "leverage": f.leverage,
            "score_formula_version": score.formula_version if score is not None else None,
            "score_weights_version": score.weights_version if score is not None else None,
        }
        return {
            "list_name": list_name,
            "ticker": t,
            "tier": tier,
            "rule_ids": rule_ids,
            "tags": rules.build_tags(f, tier, list_name, deep_pullback, market, sector_tag),
            "composite": info.get("composite"),
            "overall_score": f.overall_score,
            "steps_score": f.steps_score,
            "overall_verdict": f.overall_verdict,
            "weinstein_stage": f.stage,
            "vs_ma_pct": f.vs_ma_pct,
            "ma_slope_pct": f.ma_slope_pct,
            "mansfield_rs": f.mansfield_rs,
            "momentum_rank": f.momentum_rank,
            "close": p.close if p else None,
            "atr": p.atr if p else None,
            "adv_usd": p.adv_usd if p else None,
            "sector": sector_name,
            "inputs": inputs,
        }

    momentum_rows = _sorted_momentum(
        [build_row(t, rules.LIST_MOMENTUM, p.rule_ids, p.deep_pullback) for t, p in listed.items() if p.list_name == rules.LIST_MOMENTUM]
    )
    reversal_rows = _sorted_reversal(
        [build_row(t, rules.LIST_REVERSAL, p.rule_ids, False) for t, p in listed.items() if p.list_name == rules.LIST_REVERSAL]
    )
    overlap = {r["ticker"] for r in momentum_rows} & {r["ticker"] for r in reversal_rows}
    if overlap:  # unreachable while assign_list is the only router; a refusal beats freezing a contradictory run
        raise OpportunityRunRefused(f"a ticker landed on both lists: {sorted(overlap)}. Nothing written.")
    rows = []
    for ordered in (momentum_rows, reversal_rows):
        for order, row in enumerate(ordered, start=1):
            row["list_order"] = order
            rows.append(row)

    # The pool: every gate-passing ticker with the list its stage allows and whether it made one. Stored only (nothing reads it yet).
    listed_on = {r["ticker"]: r["list_name"] for r in rows}
    pool = []
    for t in passed:
        f = features[t]
        p = f.price
        score = scores.get(t)
        info = rank_info.get(t, {})
        pool.append(
            {
                "ticker": t,
                "tier": tiers[t],
                "assigned_list": rules.assign_list(f),
                "listed": t in listed_on,
                "list_name": listed_on.get(t),
                "sector": score.sector if score is not None and not f.is_etf else None,
                "overall_verdict": f.overall_verdict,
                "weinstein_stage": f.stage,
                "vs_ma_pct": f.vs_ma_pct,
                "momentum_rank": f.momentum_rank,
                "close": p.close if p else None,
                "adv_usd": p.adv_usd if p else None,
                "inputs": {
                    "is_etf": f.is_etf,
                    "leverage": f.leverage,
                    "pending_direction": f.pending_direction,
                    "weeks_in_advance": f.weeks_in_advance,
                    "ma_slope_pct": f.ma_slope_pct,
                    "mansfield_rs": f.mansfield_rs,
                    "return_3m": f.return_3m,
                    "return_12m": f.return_12m,
                    "composite": info.get("composite"),
                    "momentum_group": group_of.get(t),
                    "momentum_group_size": f.momentum_group_size,
                    "drawdown_pct": p.drawdown_pct if p else None,
                    "signal_status": f.signal_status,
                    "overall_score": f.overall_score,
                },
            }
        )

    counts: dict[str, dict[str, dict[str, int]]] = {rules.LIST_MOMENTUM: {}, rules.LIST_REVERSAL: {}}
    for row in rows:
        by_tier = counts[row["list_name"]].setdefault(row["tier"], {"total": 0})
        by_tier["total"] += 1
        for rid in row["rule_ids"]:
            by_tier[rid] = by_tier.get(rid, 0) + 1
    quality_passed = [t for t in passed if tiers[t] == rules.TIER_QUALITY]
    summary = {
        "counts": counts,
        "list_totals": {name: len(r) for name, r in ((rules.LIST_MOMENTUM, momentum_rows), (rules.LIST_REVERSAL, reversal_rows))},
        "ranked_universe": ranked_sizes,
        "gate_passed": len(passed),
        "pool_rows": len(pool),
        "gate_drops": gate_drops,
        "stale_stage_rows": stale_stage,
        "stale_score_rows": stale_scores,
        "quality_not_covered": sum(1 for t in quality_passed if features[t].signal_status == rules.SIGNAL_NOT_COVERED),
        "quality_total": len(quality_passed),
        "deep_pullback": sum(1 for r in momentum_rows if r["tags"].get("deep_pullback")),
        "stage_split": {
            "momentum_stage": sum(1 for t in passed if rules.assign_list(features[t]) == rules.LIST_MOMENTUM),
            "reversal_stage": sum(1 for t in passed if rules.assign_list(features[t]) == rules.LIST_REVERSAL),
            "neither": sum(1 for t in passed if rules.assign_list(features[t]) is None),
        },
        "rs_benchmark": rs_benchmark,
        "market": market_context,
        "limits": {"signal_window_start": _signal_window_start(as_of).isoformat()},
    }
    last_bar = max((f.price.last_bar_date for f in features.values() if f.price is not None), default=as_of)
    return ComputedRun(
        as_of=as_of,
        last_bar_date=last_bar,
        universe_size=len(universe),
        score_formula_version=SCORE_FORMULA_VERSION,
        weights_version=weights_version,
        summary=summary,
        rows=rows,
        pool=pool,
        gate_drops=gate_drops,
    )


def _exchanges_for(tickers: list[str]) -> dict[str, str | None]:
    with Session(engine) as session:
        return _exchanges(session, tickers)


# --- persistence --------------------------------------------------------------------------------------------------------------


def find_run(session: Session, as_of: date, kind: str = KIND_WEEKLY) -> OpportunityRun | None:
    return session.exec(select(OpportunityRun).where(OpportunityRun.kind == kind, OpportunityRun.as_of_date == as_of)).first()


def existing_run_id(as_of: date, kind: str = KIND_WEEKLY) -> int | None:
    """The id of the stored run for (kind, as_of), or None. Lets the job skip the whole computation on a rerun."""
    with Session(engine) as session:
        run = find_run(session, as_of, kind)
        return run.id if run is not None else None


def persist_run(computed: ComputedRun, force: bool = False, kind: str = KIND_WEEKLY, now: datetime | None = None) -> dict:
    """Inserts the run and its rows. A run for (kind, as_of) that already exists is a no-op (`{"status": "exists"}`) unless
    `force`, which deletes that run and the rows keyed by its run id (snapshot rows, pool rows, outcome rows, pool outcome rows) and inserts the new ones
    in ONE transaction (nothing is left half-replaced if anything fails). The pool is written in that same transaction. Picks are
    NEVER deleted: they are keyed by (as_of_date, ticker), not by run id, so they outlive the rebuilt run. The deleted counts come
    back as `deleted`. Nothing else is ever written or updated."""
    now = now or datetime.now()
    with Session(engine) as session:
        existing = find_run(session, computed.as_of, kind)
        if existing is not None and not force:
            return {"status": "exists", "run_id": existing.id, "as_of_date": computed.as_of.isoformat()}
        replaced = existing.id if existing is not None else None
        deleted: dict[str, int] = {}
        try:
            if existing is not None:
                for label, model in (
                    ("snapshot_rows", OpportunitySnapshotRow),
                    ("pool_rows", OpportunityPoolRow),
                    ("outcome_rows", OpportunityOutcome),
                    ("pool_outcome_rows", OpportunityPoolOutcome),
                ):
                    deleted[label] = session.exec(delete(model).where(model.run_id == existing.id)).rowcount
                session.exec(delete(OpportunityRun).where(OpportunityRun.id == existing.id))
            run = OpportunityRun(
                kind=kind,
                as_of_date=computed.as_of,
                last_bar_date=computed.last_bar_date,
                universe_size=computed.universe_size,
                rules_hash=rules.rules_hash(),
                rules_version=rules.RULES_VERSION,
                score_formula_version=computed.score_formula_version,
                weights_version=computed.weights_version,
                created_at=now,
                summary_json=json.dumps(computed.summary),
            )
            session.add(run)
            session.flush()
            for row in computed.rows:
                session.add(
                    OpportunitySnapshotRow(
                        run_id=run.id,
                        list_name=row["list_name"],
                        ticker=row["ticker"],
                        tier=row["tier"],
                        list_order=row["list_order"],
                        rule_ids_json=json.dumps(row["rule_ids"]),
                        tags_json=json.dumps(row["tags"]),
                        overall_score=row["overall_score"],
                        steps_score=row["steps_score"],
                        overall_verdict=row["overall_verdict"],
                        weinstein_stage=row["weinstein_stage"],
                        vs_ma_pct=row["vs_ma_pct"],
                        ma_slope_pct=row["ma_slope_pct"],
                        mansfield_rs=row["mansfield_rs"],
                        momentum_rank=row["momentum_rank"],
                        close=row["close"],
                        atr=row["atr"],
                        adv_usd=row["adv_usd"],
                        sector=row["sector"],
                        inputs_json=json.dumps(row["inputs"]),
                    )
                )
            for p in computed.pool:
                session.add(
                    OpportunityPoolRow(
                        run_id=run.id,
                        ticker=p["ticker"],
                        tier=p["tier"],
                        assigned_list=p["assigned_list"],
                        listed=p["listed"],
                        list_name=p["list_name"],
                        sector=p["sector"],
                        overall_verdict=p["overall_verdict"],
                        weinstein_stage=p["weinstein_stage"],
                        vs_ma_pct=p["vs_ma_pct"],
                        momentum_rank=p["momentum_rank"],
                        close=p["close"],
                        adv_usd=p["adv_usd"],
                        inputs_json=json.dumps(p["inputs"]),
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        return {
            "status": "replaced" if replaced is not None else "created",
            "run_id": run.id,
            "replaced_run_id": replaced,
            "as_of_date": computed.as_of.isoformat(),
            "rows": len(computed.rows),
            "pool_rows": len(computed.pool),
            "deleted": deleted,
        }


PICK_SOURCE_PAGE = "opportunities_page"


def record_picks(session: Session, run_id: int | None, tickers: list[str], source: str = PICK_SOURCE_PAGE, now: datetime | None = None) -> int:
    """Records that the user CHOSE these tickers from the weekly run `run_id` (the Opportunities page's manual Add to watchlist). The
    run is resolved here to its `as_of_date` and the pick is stored under (as_of_date, ticker): it survives a rebuilt run. Insert-only
    and idempotent: a (as_of_date, ticker) already picked is left alone. Only tickers that are rows of that run are recorded (an
    unknown run id, or a ticker the run never listed, is ignored, not an error). Returns the number of new pick rows. Never raises: a
    pick must not break the watchlist add it rides on, so a failure is logged and rolled back."""
    if run_id is None or not tickers:
        return 0
    try:
        run = session.get(OpportunityRun, run_id)
        if run is None or run.kind != KIND_WEEKLY:
            return 0
        listed = set(session.exec(select(OpportunitySnapshotRow.ticker).where(OpportunitySnapshotRow.run_id == run_id)).all())
        wanted = {t for t in tickers if t in listed}
        if not wanted:
            return 0
        already = set(session.exec(select(OpportunityPick.ticker).where(OpportunityPick.as_of_date == run.as_of_date)).all())
        picked_at = now or datetime.now()
        new = sorted(wanted - already)
        for ticker in new:
            session.add(OpportunityPick(as_of_date=run.as_of_date, ticker=ticker, picked_at=picked_at, source=source))
        session.commit()
        return len(new)
    except Exception:  # noqa: BLE001 -- see the docstring
        session.rollback()
        logger.warning("Could not record opportunity picks for run %s (%s).", run_id, tickers, exc_info=True)
        return 0


# --- reading (the API) ----------------------------------------------------------------------------------------------------------


def _row_out(row: OpportunitySnapshotRow) -> OpportunityRowOut:
    inputs = json.loads(row.inputs_json)
    return OpportunityRowOut(
        ticker=row.ticker,
        company_name=inputs.get("company_name"),
        list_name=row.list_name,
        tier=row.tier,
        list_order=row.list_order,
        rule_ids=json.loads(row.rule_ids_json),
        tags=json.loads(row.tags_json),
        overall_score=row.overall_score,
        steps_score=row.steps_score,
        overall_verdict=row.overall_verdict,
        weinstein_stage=row.weinstein_stage,
        vs_ma_pct=row.vs_ma_pct,
        ma_slope_pct=row.ma_slope_pct,
        mansfield_rs=row.mansfield_rs,
        momentum_rank=row.momentum_rank,
        close=row.close,
        atr=row.atr,
        adv_usd=row.adv_usd,
        sector=row.sector,
        exchange=inputs.get("exchange"),
        weeks_in_advance=inputs.get("weeks_in_advance"),
        inputs=inputs,
    )


def _run_out(session: Session, run: OpportunityRun) -> OpportunityRunOut:
    rows = session.exec(
        select(OpportunitySnapshotRow).where(OpportunitySnapshotRow.run_id == run.id).order_by(OpportunitySnapshotRow.list_name, OpportunitySnapshotRow.list_order)
    ).all()
    out = [_row_out(r) for r in rows]
    return OpportunityRunOut(
        id=run.id,
        kind=run.kind,
        as_of_date=run.as_of_date,
        last_bar_date=run.last_bar_date,
        universe_size=run.universe_size,
        rules_hash=run.rules_hash,
        rules_version=run.rules_version,
        score_formula_version=run.score_formula_version,
        weights_version=run.weights_version,
        created_at=run.created_at,
        summary=json.loads(run.summary_json),
        rule_labels=rules.RULE_LABELS,
        momentum=[r for r in out if r.list_name == rules.LIST_MOMENTUM],
        reversal=[r for r in out if r.list_name == rules.LIST_REVERSAL],
    )


def get_run(as_of: date | None = None, kind: str = KIND_WEEKLY) -> OpportunityRunOut | None:
    """The run for `as_of`, or the latest one when `as_of` is None. None when there is none. Reads only."""
    with Session(engine) as session:
        stmt = select(OpportunityRun).where(OpportunityRun.kind == kind)
        stmt = stmt.where(OpportunityRun.as_of_date == as_of) if as_of is not None else stmt.order_by(OpportunityRun.as_of_date.desc()).limit(1)
        run = session.exec(stmt).first()
        return _run_out(session, run) if run is not None else None


def list_run_dates(kind: str = KIND_WEEKLY) -> list[OpportunityDateOut]:
    """Every run's date, newest first, with its two list sizes. Reads only."""
    with Session(engine) as session:
        runs = session.exec(select(OpportunityRun).where(OpportunityRun.kind == kind).order_by(OpportunityRun.as_of_date.desc())).all()
        counts = {
            (run_id, list_name): n
            for run_id, list_name, n in session.exec(
                select(OpportunitySnapshotRow.run_id, OpportunitySnapshotRow.list_name, func.count()).group_by(
                    OpportunitySnapshotRow.run_id, OpportunitySnapshotRow.list_name
                )
            ).all()
        }
        return [
            OpportunityDateOut(
                as_of_date=r.as_of_date,
                kind=r.kind,
                created_at=r.created_at,
                momentum_count=counts.get((r.id, rules.LIST_MOMENTUM), 0),
                reversal_count=counts.get((r.id, rules.LIST_REVERSAL), 0),
            )
            for r in runs
        ]
