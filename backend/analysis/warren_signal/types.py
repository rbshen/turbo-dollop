"""Shared dataclasses for the Warren RSI/ADX/WVF engine (see state_machine.py)
-- mirrors analysis/entry_signal/types.py's dataclass-based style for
structured returns.
"""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

# ThinkScript defaults shared by every per-ticker profile (the same literals appear in all four scripts).
ADX_BETWEEN_HI = 46.0  # Between(ADX, <lo>, 46)
SOS2_ADX_MAX = 29.66  # scanOverSold2 branch a: ADX <= 29.66
SOS2_RSI_A_MAX = 40.0  # scanOverSold2 branch a: RSI_Num < 40 (current bar, strict)
PARA_DROP_MAX = 0.70  # scanOverSold2 branch c: paraDrop <= .70

# Every buy/sell arrow this engine can fire. Up-kinds are buy-side
# (scanOverSold3/scanOverSold4-derived), Down-kinds are sell-side
# (bear1/wvf+rsiOverbought/rsi84.75/rsiOverbought-derived). Order here has
# no semantic meaning -- membership is what matters (see
# state_machine.py::UP_KINDS).
SIGNAL_KINDS = ("blue_up", "yellow_up", "gray_up", "blue_down", "yellow_down", "gray_down")


@dataclass(frozen=True)
class WarrenSignalEvent:
    """One fired arrow. `stop_price` is the LIVE yellowStopPrice as of this
    bar (see state_machine.py's own module docstring for why this can differ
    from "the stop this specific event set") -- may be None if no yellow/gray
    entry has ever been held yet."""

    kind: str  # one of SIGNAL_KINDS
    fired_at: datetime
    close: float
    rsi: float | None
    stop_price: float | None


@dataclass(frozen=True)
class WarrenReplayResult:
    """One full nightly replay's outcome for a ticker -- NOT incremental
    state (see state_machine.py's own docstring): every field here is
    recomputed from scratch every run, from the full available history.

    events: every arrow that fired anywhere in the given history, in
    chronological order (oldest first) -- unlike TechnicalEntrySignal's own
    "latest fire only" semantics, this is the complete list; the caller
    (data/warren_signal_data.py) is responsible for both storing the full
    list (into WarrenSignalEvent) and deriving "latest state" from its tail.

    as_of: the last candle actually evaluated this run, regardless of
    whether anything fired on it.

    gray_suppressed/stop_count/live_stop_price: the state machine's own
    internal state AS OF THE LAST REPLAYED BAR -- i.e. the standing
    "current" reference for the next signal, independent of which bar the
    latest EVENT in `events` happens to have landed on. gray_suppressed
    mirrors yellowIsGray; stop_count mirrors stopCount; live_stop_price
    mirrors yellowStopPrice (None if no yellow/gray entry has ever been
    held)."""

    as_of: datetime
    events: list[WarrenSignalEvent]
    gray_suppressed: bool
    stop_count: int
    live_stop_price: float | None


@dataclass(frozen=True)
class WarrenSeries:
    """The indicator series the state machine reads, exposed so a chart can plot exactly what drove the
    arrows (the same objects replay() used -- not a second calculation). All share the candles' index;
    leading values are NaN until each indicator's warm-up completes. `wvf` is wvfBuy
    ((highest close over 22 bars - low) / highest close * 100), the only WVF the state machine uses."""

    rsi: pd.Series
    plus_di: pd.Series
    minus_di: pd.Series
    adx: pd.Series
    wvf: pd.Series


@dataclass(frozen=True)
class QuietBlueBranch:
    """One operand of scanOverSold1 (the "quiet bar" Blue): `RSI_Num[1] <= rsi1_max [and WVF_Buy >= wvf_min]
    and ADX_Between and volume <= volume_max`. All comparisons are inclusive (`<=` / `>=`), and so is
    ADX_Between."""

    rsi1_max: float
    volume_max: float
    wvf_min: float | None = None  # branch a only; None = no WVF term


@dataclass(frozen=True)
class TickerBlueRules:
    """A per-ticker Blue Up definition, transcribed from that ticker's ThinkScript:

        blueUp = scanOverSold1 or scanOverSold2
        scanOverSold1 = <quiet branch a> or <quiet branch b>                       (see QuietBlueBranch)
        scanOverSold2 = volume > Volume_Num and ADX <= 29.66 and RSI_Num < 40          (branch a)
                     or RSI_Num < sos2_rsi_b and volume > Volume_Num                 (branch b)
                     or paraDrop <= .70 and pivotLow and WVF_Between(25, 27)          (branch c)
                     [or RSI_Num[1] < ungated_rsi1_lt]      (QQQ only; no volume/ADX gate)
                     [or WVF_Buy >= ungated_wvf_min]        (QQQ only; no volume/ADX gate)

    `and` binds tighter than `or` (see indicators.compute_blue, which spells every grouping out)."""

    adx_lo: float  # ADX_Between(ADX, adx_lo, 46)
    quiet_branches: tuple[QuietBlueBranch, ...]  # scanOverSold1 operands (a, b)
    volume_num: float  # Volume_Num: the SOS2 "panic bar" volume floor (strict >)
    sos2_rsi_b: float  # scanOverSold2 branch b: RSI_Num < this (current bar, strict)
    ungated_rsi1_lt: float | None = None  # trailing OR: RSI_Num[1] < x
    ungated_wvf_min: float | None = None  # trailing OR: WVF_Buy >= x
    adx_hi: float = ADX_BETWEEN_HI
    sos2_adx_max: float = SOS2_ADX_MAX
    sos2_rsi_a_max: float = SOS2_RSI_A_MAX
    para_drop_max: float = PARA_DROP_MAX


@dataclass(frozen=True)
class WarrenProfile:
    """Which Blue Up definition the replay uses. `rules is None` is the ANY-TICKER definition
    (scanOverSold4: `RSI_Num[1] <= blue_rsi1_max`), which needs no volume. A profile with `rules` replaces it
    entirely -- the per-ticker scripts have no scanOverSold4. Everything else in the state machine (Yellow/Gray,
    stops, every down arrow) is identical across all five scripts and is NOT profile-dependent. The engine
    never sees a ticker symbol, only the profile it is handed; the symbol -> profile lookup lives in
    data/warren_signal_data.py::profile_for."""

    name: str
    blue_rsi1_max: float = 12.0
    rules: TickerBlueRules | None = None


# The default Blue Up definition (scanOverSold4, `RSI_Num[1] <= 12`) -- what every ticker without its own
# profile uses. Its threshold is pinned equal to indicators.SCAN_BLUE_RSI_THRESHOLD by a test.
ANY_TICKER = WarrenProfile(name="any")
