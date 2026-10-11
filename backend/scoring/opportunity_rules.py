"""Pure rules of the weekly opportunity agent -- no DB, no HTTP. Spec: docs/specs/opportunities.md. Orchestration (what to load,
what to persist) is data/opportunity_data.py; the cron-style entry point is pipeline/weekly_opportunity_snapshot.py.

Two frozen lists are built across the whole universe from STORED data only:

  Momentum (list A)  stage Advance, a rising stage MA, Mansfield RS > 0, not extended (tier-specific ceiling; the junk-rally guards
                     for the Momentum-only tier), and a momentum-rank cut for Momentum-only stocks and ETFs.
  Reversal (list B)  B1 a Base (or a pending Advance) stage, B2 a price structure that has stopped falling, B3 a Warren / BB+RSI
                     entry signal in the last 10 sessions while the stage is Decline or Base. B1 and B3 are Quality only.

Every rule has a versioned id (RULE_IDS). `rules_hash()` is the sha256 of the canonical definitions (ids + every threshold below),
stored on each run, so a later change to any constant is visible on the runs that used the old one: change a threshold, bump
RULES_VERSION. The thresholds are the ones of the 2026-10-11 preview, tightened where the approved brief says so.

Tiers: Quality = stored Overall verdict Pass or Strong Pass (QUALITY_VERDICTS; "Pass with caution" is NOT in it, as in the
preview), Momentum-only = every other stock, ETF = the ETF universe. The stored verdict key "Fail" is never changed here: the
display word "May not pass" is the frontend's job (lib/tierColor.ts)."""

import hashlib
import json
import math
import re
from fractions import Fraction
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from analysis.trend_structure.weinstein import WeinsteinParams, compute_stage_series, resample_to_weekly

RULES_VERSION = "1"

LIST_MOMENTUM = "momentum"
LIST_REVERSAL = "reversal"

TIER_QUALITY = "quality"
TIER_MOMENTUM_ONLY = "momentum_only"
TIER_ETF = "etf"

# --- versioned rule ids ------------------------------------------------------------------------------------------------
RULE_A = "A.momentum_trend.v1"
RULE_B1 = "B1.base_or_pending_advance.v1"
RULE_B2 = "B2.price_structure.v1"
RULE_B3 = "B3.entry_signal.v1"
RULE_IDS = (RULE_A, RULE_B1, RULE_B2, RULE_B3)
# What the Reversal tab shows in the "Rule" column, and the Momentum tab's tooltip.
RULE_LABELS = {
    RULE_A: "Momentum trend",
    RULE_B1: "Base or pending advance",
    RULE_B2: "Price structure",
    RULE_B3: "Entry signal",
}

# --- gate (all tiers) --------------------------------------------------------------------------------------------------
EXCLUDED_TICKERS = frozenset({"SPY"})  # the benchmark: its RS against itself is 0, it can never qualify
MIN_HISTORY_MONTHS = 12
ADV_SESSIONS = 50
MIN_ADV_USD = 25_000_000.0  # average daily dollar volume over ADV_SESSIONS sessions

GATE_EXCLUDED = "excluded"
GATE_DELISTED = "delisted"
GATE_NO_BARS = "no_bars"
GATE_STALE_BAR = "stale_bar"
GATE_PROVISIONAL_BAR = "provisional_bar"
GATE_SHORT_HISTORY = "short_history"
GATE_ILLIQUID = "illiquid"

# --- tiers -------------------------------------------------------------------------------------------------------------
QUALITY_VERDICTS = frozenset({"Pass", "Strong Pass"})

# --- list A, Momentum ---------------------------------------------------------------------------------------------------
A_VS_MA_CEILING_PCT = {TIER_QUALITY: 20.0, TIER_ETF: 20.0, TIER_MOMENTUM_ONLY: 15.0}  # strictly below
MOMENTUM_ONLY_MAX_WEEKS_IN_ADVANCE = 52
MOMENTUM_ONLY_MAX_RETURN_3M = 0.30
MOMENTUM_ONLY_MAX_RETURN_12M = 1.50
MOMENTUM_ONLY_TOP_FRACTION = Fraction(1, 5)  # top quintile of the ranked stock universe (exact: ceil(575 x 0.2) in floats is 116)
ETF_TOP_FRACTION = Fraction(1, 3)  # top third of the ETF's own group (ordinary ETFs, or leveraged ETFs, ranked separately)
LATE_TREND_WEEKS = 52  # tag only: "late trend" at >= this many weeks in Advance

# --- list B, Reversal ----------------------------------------------------------------------------------------------------
B2_MIN_DRAWDOWN_PCT = {TIER_QUALITY: 20.0, TIER_ETF: 20.0, TIER_MOMENTUM_ONLY: 30.0}  # from the 52-week high
B2_HIGH_WINDOW_SESSIONS = 252
B2_TROUGH_WINDOW_SESSIONS = 126  # the trough is the lowest low of these sessions
B2_TROUGH_MIN_AGE_SESSIONS = 15  # ... and must be at least this old
B2_RECENT_LOW_SESSIONS = 15  # the higher low: the last 15 sessions' lowest low is above the trough
B2_WEEKLY_SMA = 10  # the weekly close must be above its 10-week SMA
B2_SLOPE_LOOKBACK_WEEKS = 4  # the 30-week EMA slope must be above its value this many weeks ago ...
B2_SLOPE_FLOOR_PCT = -2.0  # ... and at least this (percent over the engine's slope lookback)
B2_MIN_WEEKLY_BARS = 40
B3_SIGNAL_WINDOW_SESSIONS = 10
B3_STAGES = frozenset({"decline", "base"})
B3_WARREN_KINDS = ("blue_up", "yellow_up")

SIGNAL_FIRED = "fired"
SIGNAL_NONE = "no_signal"
SIGNAL_NOT_COVERED = "not_covered"  # no event in the window and the ticker is on no monitored watchlist: the signal jobs never ran for it

# --- tags -------------------------------------------------------------------------------------------------------------
HELD_BACK_FUNDAMENTALS_MIN = 70.0  # blended Fundamentals at or above this, Overall below PASS_THRESHOLD
PASS_THRESHOLD = 70
STEP_LABELS = {"step1": "Financials", "step2": "Growth rate", "step4": "Profitability", "step5": "Debt"}

# Leveraged ETFs: ranked apart from ordinary ETFs and tagged. A curated factor by ticker, plus a name test for the rest.
LEVERAGED_ETF_FACTORS = {"TQQQ": 3, "SQQQ": 3, "SOXL": 3, "SOXS": 3, "TECL": 3, "TECS": 3, "UPRO": 3, "SPXL": 3, "FNGU": 3, "LABU": 3, "QLD": 2, "SSO": 2, "USD": 2}
_LEVERAGE_NAME = re.compile(r"\b([23])x\b|\bultrapro\b", re.IGNORECASE)


def leverage_factor(ticker: str, name: str | None) -> int | None:
    """2 or 3 for a leveraged fund, else None. The curated map wins; a fund name such as "Direxion Daily Semiconductor Bull 3X
    ETF" or "ProShares UltraPro QQQ" (UltraPro = 3x) is read otherwise."""
    if ticker in LEVERAGED_ETF_FACTORS:
        return LEVERAGED_ETF_FACTORS[ticker]
    if not name:
        return None
    match = _LEVERAGE_NAME.search(name)
    if match is None:
        return None
    return int(match.group(1)) if match.group(1) else 3


def rules_definition() -> dict:
    """The canonical, JSON-able definition of every rule and threshold: what `rules_hash` digests."""
    return {
        "version": RULES_VERSION,
        "rule_ids": list(RULE_IDS),
        "gate": {
            "excluded": sorted(EXCLUDED_TICKERS),
            "min_history_months": MIN_HISTORY_MONTHS,
            "adv_sessions": ADV_SESSIONS,
            "min_adv_usd": MIN_ADV_USD,
            "last_bar_equals_as_of": True,
            "not_delisted": True,
        },
        "tiers": {"quality_verdicts": sorted(QUALITY_VERDICTS), "etf": "ETF universe", "momentum_only": "every other stock"},
        "A": {
            "stage": "advance",
            "ma_slope_pct_gt": 0,
            "mansfield_rs_gt": 0,
            "vs_ma_pct_lt": A_VS_MA_CEILING_PCT,
            "momentum_only": {
                "max_weeks_in_advance": MOMENTUM_ONLY_MAX_WEEKS_IN_ADVANCE,
                "max_return_3m": MOMENTUM_ONLY_MAX_RETURN_3M,
                "max_return_12m": MOMENTUM_ONLY_MAX_RETURN_12M,
                "top_fraction_of_ranked_stocks": str(MOMENTUM_ONLY_TOP_FRACTION),
            },
            "etf": {"top_fraction_of_own_group": str(ETF_TOP_FRACTION), "leveraged_ranked_separately": True},
            "late_trend_weeks_tag": LATE_TREND_WEEKS,
        },
        "B1": {"tiers": [TIER_QUALITY], "stage": "base", "or_pending_direction": "advance"},
        "B2": {
            "min_drawdown_pct_from_52w_high": B2_MIN_DRAWDOWN_PCT,
            "high_window_sessions": B2_HIGH_WINDOW_SESSIONS,
            "trough_window_sessions": B2_TROUGH_WINDOW_SESSIONS,
            "trough_min_age_sessions": B2_TROUGH_MIN_AGE_SESSIONS,
            "recent_low_sessions": B2_RECENT_LOW_SESSIONS,
            "weekly_close_above_sma": B2_WEEKLY_SMA,
            "ema_slope_above_weeks_ago": B2_SLOPE_LOOKBACK_WEEKS,
            "ema_slope_floor_pct": B2_SLOPE_FLOOR_PCT,
            "weinstein_params": "WeinsteinParams() defaults",
        },
        "B3": {
            "tiers": [TIER_QUALITY],
            "window_sessions": B3_SIGNAL_WINDOW_SESSIONS,
            "warren_kinds": list(B3_WARREN_KINDS),
            "or_bb_rsi": True,
            "stages": sorted(B3_STAGES),
            "uncovered": SIGNAL_NOT_COVERED,
        },
        "tags": {"held_back_fundamentals_min": HELD_BACK_FUNDAMENTALS_MIN, "leveraged_etfs": sorted(LEVERAGED_ETF_FACTORS)},
    }


def rules_hash() -> str:
    return hashlib.sha256(json.dumps(rules_definition(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- bar-derived features ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceFeatures:
    first_bar_date: date
    last_bar_date: date
    n_bars: int
    close: float
    adv_usd: float | None  # mean of close x volume over the last ADV_SESSIONS sessions; None below that many bars
    atr: float | None  # Wilder ATR(14) of the daily bars
    drawdown_pct: float | None  # (1 - close / 52-week high) x 100
    higher_low: bool | None
    above_10w_sma: bool | None
    ma_slope_now: float | None  # the Weinstein MA slope (percent) of the last weekly bar
    ma_slope_4w_ago: float | None


def _atr(bars: pd.DataFrame, length: int = 14) -> float | None:
    if len(bars) < length + 1:
        return None
    prev_close = bars["close"].shift(1)
    true_range = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - prev_close).abs(), (bars["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return float(true_range.iloc[1:].ewm(alpha=1 / length, adjust=False).mean().iloc[-1])


def compute_price_features(bars: pd.DataFrame, as_of: date, params: WeinsteinParams | None = None) -> PriceFeatures | None:
    """Everything the rules need from one ticker's daily bars (lowercase OHLCV, naive DatetimeIndex), looking at bars on or before
    `as_of` only. None when there are none. A figure the history is too short for is None, never imputed."""
    params = params or WeinsteinParams()
    bars = bars.loc[bars.index <= pd.Timestamp(as_of)]
    if bars.empty:
        return None
    n = len(bars)
    close = bars["close"]
    last_close = float(close.iloc[-1])

    adv = float((close * bars["volume"]).tail(ADV_SESSIONS).mean()) if n >= ADV_SESSIONS else None

    drawdown = higher_low = above_sma = slope_now = slope_then = None
    if n >= B2_TROUGH_WINDOW_SESSIONS:
        high = float(bars["high"].tail(min(B2_HIGH_WINDOW_SESSIONS, n)).max())
        drawdown = (1 - last_close / high) * 100 if high > 0 else None
        lows = bars["low"].tail(B2_TROUGH_WINDOW_SESSIONS)
        trough_age = len(lows) - 1 - int(lows.to_numpy().argmin())
        higher_low = bool(trough_age >= B2_TROUGH_MIN_AGE_SESSIONS and bars["low"].tail(B2_RECENT_LOW_SESSIONS).min() > lows.min())
    weekly = resample_to_weekly(bars)
    if len(weekly) >= B2_MIN_WEEKLY_BARS:
        weekly_close = weekly["close"]
        sma = weekly_close.rolling(B2_WEEKLY_SMA).mean().iloc[-1]
        above_sma = bool(weekly_close.iloc[-1] > sma) if pd.notna(sma) else None
        slope = compute_stage_series(weekly_close, params)["slope"]
        now, then = slope.iloc[-1], slope.iloc[-1 - B2_SLOPE_LOOKBACK_WEEKS]
        slope_now = float(now) if pd.notna(now) else None
        slope_then = float(then) if pd.notna(then) else None

    return PriceFeatures(
        first_bar_date=bars.index[0].date(),
        last_bar_date=bars.index[-1].date(),
        n_bars=n,
        close=last_close,
        adv_usd=adv,
        atr=_atr(bars),
        drawdown_pct=drawdown,
        higher_low=higher_low,
        above_10w_sma=above_sma,
        ma_slope_now=slope_now,
        ma_slope_4w_ago=slope_then,
    )


# --- one ticker's inputs ------------------------------------------------------------------------------------------------


@dataclass
class Features:
    """Everything the rules read for one ticker. A field that is None is unknown and fails any rule that needs it."""

    ticker: str
    is_etf: bool = False
    leverage: int | None = None
    delisted: bool = False
    price: PriceFeatures | None = None
    provisional_last_bar: bool = False
    # stored scores (TickerScore); None for an ETF
    overall_verdict: str | None = None
    overall_score: int | None = None
    steps_score: float | None = None
    moat: str | None = None
    moat_multiplier: float | None = None
    step_scores: dict[str, int | None] = field(default_factory=dict)  # keyed step1/step2/step4/step5
    step_verdicts: dict[str, str | None] = field(default_factory=dict)
    # the stored stage engine row (TrendAnalysis) -- None when the row is missing or not as of the run's date
    stage: str | None = None
    pending_direction: str | None = None
    weeks_in_advance: int | None = None
    ma_slope_pct: float | None = None
    vs_ma_pct: float | None = None
    mansfield_rs: float | None = None
    # momentum ranking (scoring/momentum.py): rank within the ticker's own ranked group
    momentum_rank: int | None = None
    momentum_group_size: int | None = None
    return_3m: float | None = None
    return_12m: float | None = None
    # B3
    signal_status: str = SIGNAL_NOT_COVERED


def gate_reason(f: Features, as_of: date) -> str | None:
    """None when the ticker passes the gate, else the reason code. Order: excluded, delisted, no bars, stale last bar (not
    `as_of`), provisional last bar, under 12 months of history, under the dollar-volume floor."""
    if f.ticker in EXCLUDED_TICKERS:
        return GATE_EXCLUDED
    if f.delisted:
        return GATE_DELISTED
    p = f.price
    if p is None:
        return GATE_NO_BARS
    if p.last_bar_date != as_of:
        return GATE_STALE_BAR
    if f.provisional_last_bar:
        return GATE_PROVISIONAL_BAR
    if p.first_bar_date > (pd.Timestamp(as_of) - pd.DateOffset(months=MIN_HISTORY_MONTHS)).date():
        return GATE_SHORT_HISTORY
    if p.adv_usd is None or p.adv_usd < MIN_ADV_USD:
        return GATE_ILLIQUID
    return None


def tier_for(f: Features) -> str:
    if f.is_etf:
        return TIER_ETF
    return TIER_QUALITY if f.overall_verdict in QUALITY_VERDICTS else TIER_MOMENTUM_ONLY


def _top_cut(group_size: int | None, fraction: Fraction) -> int | None:
    """The last rank inside the top `fraction` of a ranked group (rounded up: the top third of 28 is 10)."""
    return None if not group_size else math.ceil(group_size * fraction)


def momentum_rule_ids(f: Features, tier: str) -> list[str]:
    """List A. [RULE_A] when the ticker qualifies, else []. Any unknown input (no stage row, no rank, no 3m/12m return, no weeks
    in Advance) fails the rule that needs it: an unrankable ticker is never on the Momentum list."""
    if f.stage != "advance" or f.ma_slope_pct is None or f.mansfield_rs is None or f.vs_ma_pct is None:
        return []
    if not (f.ma_slope_pct > 0 and f.mansfield_rs > 0 and f.vs_ma_pct < A_VS_MA_CEILING_PCT[tier]):
        return []
    if tier == TIER_MOMENTUM_ONLY:
        if f.weeks_in_advance is None or f.weeks_in_advance > MOMENTUM_ONLY_MAX_WEEKS_IN_ADVANCE:
            return []
        if f.return_3m is None or f.return_3m > MOMENTUM_ONLY_MAX_RETURN_3M:
            return []
        if f.return_12m is None or f.return_12m > MOMENTUM_ONLY_MAX_RETURN_12M:
            return []
        cut = _top_cut(f.momentum_group_size, MOMENTUM_ONLY_TOP_FRACTION)
        if f.momentum_rank is None or cut is None or f.momentum_rank > cut:
            return []
    elif tier == TIER_ETF:
        cut = _top_cut(f.momentum_group_size, ETF_TOP_FRACTION)
        if f.momentum_rank is None or cut is None or f.momentum_rank > cut:
            return []
    return [RULE_A]


def price_structure_ok(f: Features, tier: str) -> bool:
    """B2: a deep enough drawdown from the 52-week high, a higher low, a weekly close above the 10-week SMA and a 30-week EMA
    slope that is above its value 4 weeks ago and not below -2%."""
    p = f.price
    if p is None or p.drawdown_pct is None or p.higher_low is None or p.above_10w_sma is None:
        return False
    if p.ma_slope_now is None or p.ma_slope_4w_ago is None:
        return False
    return (
        p.drawdown_pct >= B2_MIN_DRAWDOWN_PCT[tier]
        and p.higher_low
        and p.above_10w_sma
        and p.ma_slope_now > p.ma_slope_4w_ago
        and p.ma_slope_now >= B2_SLOPE_FLOOR_PCT
    )


def reversal_rule_ids(f: Features, tier: str) -> list[str]:
    """List B. Each rule that fires keeps its own id. B1 and B3 are Quality only; B3 needs a `fired` signal (a not-covered ticker
    has none and is never shown as "no signal")."""
    ids: list[str] = []
    if tier == TIER_QUALITY and (f.stage == "base" or f.pending_direction == "advance"):
        ids.append(RULE_B1)
    if price_structure_ok(f, tier):
        ids.append(RULE_B2)
    if tier == TIER_QUALITY and f.signal_status == SIGNAL_FIRED and f.stage in B3_STAGES:
        ids.append(RULE_B3)
    return ids


# --- tags (stored, never filters) -----------------------------------------------------------------------------------------


def why_not_quality(f: Features) -> dict:
    """For a Momentum-only stock: the stored Overall verdict (the raw key, "Fail" included: the frontend draws it "May not pass"),
    the steps that are below the pass line or failed, the incomplete steps and the moat status."""
    failed, incomplete = [], []
    for key, label in STEP_LABELS.items():
        score, verdict = f.step_scores.get(key), f.step_verdicts.get(key)
        if verdict == "not_supported":
            continue
        if score is None:
            incomplete.append(label)
        elif verdict == "Fail" or score < PASS_THRESHOLD:
            failed.append(label)
    return {"overall_verdict": f.overall_verdict, "failed_steps": failed, "incomplete_steps": incomplete, "moat": f.moat}


def held_back_by_moat(f: Features) -> bool:
    """Blended Fundamentals at or above 70 but Overall below 70: only the Moat multiplier (Narrow, or No moat / unrated) does it."""
    return (
        f.steps_score is not None
        and f.overall_score is not None
        and f.steps_score >= HELD_BACK_FUNDAMENTALS_MIN
        and f.overall_score < PASS_THRESHOLD
    )


def build_tags(
    f: Features,
    tier: str,
    list_name: str,
    other_list_rules: list[str],
    market: dict | None,
    sector: dict | None,
) -> dict:
    """The row's tags. Keys appear only when they apply, except `market` and `sector` (the context at the run's date)."""
    tags: dict = {}
    if f.stage == "advance" and f.weeks_in_advance is not None and f.weeks_in_advance >= LATE_TREND_WEEKS:
        tags["late_trend"] = True
    if f.is_etf and f.leverage:
        tags["leveraged"] = f.leverage
    if tier != TIER_ETF and held_back_by_moat(f):
        tags["held_back_by_moat"] = True
    if tier == TIER_MOMENTUM_ONLY:
        tags["why_not_quality"] = why_not_quality(f)
    if other_list_rules:
        tags["also_on"] = LIST_REVERSAL if list_name == LIST_MOMENTUM else LIST_MOMENTUM
    if tier == TIER_QUALITY:
        tags["signal_status"] = f.signal_status
    if market is not None:
        tags["market"] = market
    if sector is not None:
        tags["sector"] = sector
    return tags
