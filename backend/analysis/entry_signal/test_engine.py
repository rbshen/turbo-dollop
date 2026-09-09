import pandas as pd
import pytest

from analysis.entry_signal.engine import compute_entry_signal
from analysis.entry_signal.indicators import check_buy_signal, compute_bollinger_bands, compute_rsi
from analysis.entry_signal.resample import build_2h_session_candles


def _synthetic_intraday_bars(closes: list[float]) -> pd.DataFrame:
    """One bar per 2h session window (09:30/11:30/13:30/15:30 ET each day),
    so `closes` maps 1:1 onto the resulting resampled candles -- lets a test
    fully control the close-price series the engine sees without needing
    many bars per window."""
    days = pd.bdate_range("2026-01-05", periods=(len(closes) + 3) // 4 + 1, tz="America/New_York")
    times = ["09:30", "11:30", "13:30", "15:30"]
    rows = []
    i = 0
    for day in days:
        for t in times:
            if i >= len(closes):
                break
            hour, minute = (int(x) for x in t.split(":"))
            ts = day.replace(hour=hour, minute=minute)
            c = closes[i]
            rows.append({"timestamp": ts, "open": c, "high": c, "low": c, "close": c, "volume": 1000})
            i += 1
    return pd.DataFrame(rows).set_index("timestamp")


def test_compute_entry_signal_matches_manual_composition_of_its_own_pieces():
    # A long flat run followed by a sharp multi-candle decline -- exercises
    # the real resample -> RSI/BB -> check_buy_signal pipeline without
    # hand-deriving expected RSI/%B numbers (those are covered directly in
    # test_indicators.py); this test only verifies engine.py wires the
    # pieces together correctly.
    closes = [100.0] * 20 + [95.0, 90.0, 85.0, 80.0, 75.0]
    bars = _synthetic_intraday_bars(closes)

    result = compute_entry_signal(bars)

    candles = build_2h_session_candles(bars)
    close = candles["close"]
    rsi = compute_rsi(close)
    _, _, pct_b = compute_bollinger_bands(close)
    i = len(candles) - 1
    expected_fired = check_buy_signal(rsi, pct_b, i)

    assert result.fired == expected_fired
    assert result.close == pytest.approx(closes[-1])
    assert result.pct_b == pytest.approx(pct_b.iloc[i])
    assert result.rsi == pytest.approx(rsi.iloc[i])
    assert result.as_of == candles.index[i].to_pydatetime()


def test_compute_entry_signal_raises_on_no_session_bars():
    df = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
        index=pd.DatetimeIndex(["2026-01-05 20:00"], tz="America/New_York"),
    )
    with pytest.raises(ValueError):
        compute_entry_signal(df)
