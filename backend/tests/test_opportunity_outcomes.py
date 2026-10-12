"""scoring/opportunity_outcomes.py: the pure outcome engine -- entry at the next open, SPY's dates as the calendar, the 10% intraday
stop (entry bar included, gap fills at the open), pending -> complete, censoring and its sensitivity return, benchmarks."""

from datetime import date, timedelta

import pandas as pd
import pytest

from scoring import opportunity_outcomes as eng

AS_OF = date(2026, 10, 9)  # a Friday


def sessions_after(as_of: date, n: int, skip: tuple[date, ...] = ()) -> list[date]:
    """The next n weekdays after as_of, minus the given holidays."""
    out, d = [], as_of
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in skip:
            out.append(d)
    return out


def bars(rows: dict[date, tuple[float, float, float, float]]) -> pd.DataFrame:
    """{date: (open, high, low, close)} -> an OHLC frame."""
    idx = pd.DatetimeIndex(sorted(rows))
    return pd.DataFrame([rows[d.date()] for d in idx], index=idx, columns=["open", "high", "low", "close"])


def flat(dates: list[date], price: float = 100.0, drift: float = 0.0) -> dict[date, tuple[float, float, float, float]]:
    """A quiet series: open = close of the previous bar, +drift per bar, +-0.5% range."""
    rows, p = {}, price
    for d in dates:
        o, c = p, p * (1 + drift)
        rows[d] = (o, max(o, c) * 1.005, min(o, c) * 0.995, c)
        p = c
    return rows


def run(ticker_rows, dates, spy_drift=0.0, as_of_close=100.0, **kw):
    spy = bars(flat(dates, 400.0, spy_drift))
    return eng.compute_outcomes(as_of=AS_OF, as_of_close=as_of_close, ticker_bars=bars(ticker_rows) if ticker_rows else None, spy_bars=spy, **kw)


def by_h(outcomes):
    return {o.horizon: o for o in outcomes}


# --- the happy path ----------------------------------------------------------------------------------------------------------


def test_entry_is_the_next_sessions_open_and_horizon_n_is_the_nth_bar_after_the_entry_bar():
    dates = sessions_after(AS_OF, 70)
    rows = flat(dates, 100.0, 0.001)
    o = by_h(run(rows, dates))
    assert all(x.status == eng.COMPLETE for x in o.values())
    assert o[5].entry_date == dates[0] and o[5].entry_open == pytest.approx(100.0)
    assert o[5].exit_date == dates[5] and o[10].exit_date == dates[10] and o[20].exit_date == dates[20] and o[60].exit_date == dates[60]
    assert o[5].exit_close == pytest.approx(rows[dates[5]][3])
    assert o[5].forward_return == pytest.approx(1.001**6 - 1)  # six bars of +0.1%: the entry bar's own move counts


def test_spy_and_sector_returns_share_the_entry_open_and_exit_close_and_excess_is_the_difference():
    dates = sessions_after(AS_OF, 12)
    sector_rows = flat(dates, 50.0, 0.002)
    o = by_h(run(flat(dates, 100.0, 0.003), dates, spy_drift=0.001, sector_bars=bars(sector_rows), sector_etf="XLK"))[5]
    assert o.spy_return == pytest.approx(1.001**6 - 1) and o.sector_return == pytest.approx(1.002**6 - 1)
    assert o.excess_vs_spy == pytest.approx(o.forward_return - o.spy_return)
    assert o.excess_vs_sector == pytest.approx(o.forward_return - o.sector_return) and o.sector_etf == "XLK"


def test_an_etf_or_unmapped_ticker_compares_against_spy_only():
    dates = sessions_after(AS_OF, 12)
    o = by_h(run(flat(dates), dates))[5]
    assert o.sector_etf is None and o.sector_return is None and o.excess_vs_sector is None
    assert o.spy_return is not None and o.excess_vs_spy is not None


def test_a_missing_sector_bar_nulls_only_the_sector_fields():
    dates = sessions_after(AS_OF, 12)
    o = by_h(run(flat(dates), dates, sector_bars=bars(flat(dates[:3])), sector_etf="XLK"))[5]
    assert o.sector_etf == "XLK" and o.sector_return is None and o.excess_vs_sector is None and o.excess_vs_spy is not None


# --- the stop ----------------------------------------------------------------------------------------------------------------


def test_a_stop_on_the_entry_bar_itself_counts_and_fills_at_minus_ten_percent():
    dates = sessions_after(AS_OF, 8)
    rows = flat(dates)
    rows[dates[0]] = (100.0, 100.5, 89.0, 95.0)  # low 11% below the open on the entry bar
    o = by_h(run(rows, dates))[5]
    assert o.stop_hit and o.stop_date == dates[0] and o.stop_fill_return == pytest.approx(-0.10)
    assert o.worst_move == pytest.approx(-0.11)


def test_a_low_exactly_at_the_stop_price_is_a_hit():
    dates = sessions_after(AS_OF, 8)
    rows = flat(dates)
    rows[dates[2]] = (99.0, 99.5, 90.0, 95.0)
    o = by_h(run(rows, dates))[5]
    assert o.stop_hit and o.stop_date == dates[2]


def test_a_gap_below_the_stop_fills_at_the_open_not_at_minus_ten_percent():
    dates = sessions_after(AS_OF, 8)
    rows = flat(dates)
    rows[dates[3]] = (82.0, 83.0, 80.0, 81.0)  # opens 18% below the entry
    o = by_h(run(rows, dates))[5]
    assert o.stop_hit and o.stop_date == dates[3] and o.stop_fill_return == pytest.approx(-0.18)


def test_a_stop_hit_that_recovers_still_records_the_stop_and_the_buy_and_hold_return():
    dates = sessions_after(AS_OF, 8)
    rows = flat(dates)
    rows[dates[1]] = (99.0, 99.5, 88.0, 99.0)  # intraday flush through the stop...
    rows[dates[5]] = (100.0, 112.0, 99.0, 110.0)  # ...recovering to +10% at the horizon
    o = by_h(run(rows, dates))[5]
    assert o.status == eng.COMPLETE and o.stop_hit and o.stop_fill_return == pytest.approx(-0.10)
    assert o.forward_return == pytest.approx(0.10)  # buy-and-hold: the stop is recorded, never applied
    assert o.worst_move == pytest.approx(-0.12) and o.best_move == pytest.approx(0.12)


def test_the_first_stop_wins():
    dates = sessions_after(AS_OF, 8)
    rows = flat(dates)
    rows[dates[1]] = (99.0, 99.5, 89.5, 95.0)
    rows[dates[3]] = (70.0, 70.0, 60.0, 65.0)
    o = by_h(run(rows, dates))[5]
    assert o.stop_date == dates[1] and o.stop_fill_return == pytest.approx(-0.10)


def test_a_stop_is_recorded_while_the_horizon_is_still_pending_and_only_on_windows_that_contain_it():
    dates = sessions_after(AS_OF, 8)  # horizon 5 is reachable, horizon 10 is not
    rows = flat(dates)
    rows[dates[7]] = (99.0, 99.0, 85.0, 90.0)  # after the horizon-5 bar (dates[5])
    o = by_h(run(rows, dates))
    assert o[5].status == eng.COMPLETE and not o[5].stop_hit  # outside horizon 5's window
    assert o[10].status == eng.PENDING and o[10].stop_hit and o[10].stop_date == dates[7]
    assert o[10].forward_return is None and o[10].exit_date is None  # nothing but the path so far


def test_the_window_excludes_bars_after_the_horizon():
    dates = sessions_after(AS_OF, 12)
    rows = flat(dates)
    rows[dates[6]] = (100.0, 130.0, 70.0, 100.0)  # one bar past horizon 5
    o = by_h(run(rows, dates))
    assert o[5].best_move < 0.05 and o[5].worst_move > -0.05 and not o[5].stop_hit
    assert o[10].best_move == pytest.approx(0.30) and o[10].stop_hit


def test_max_drawdown_is_peak_to_trough_in_closes():
    dates = sessions_after(AS_OF, 8)
    closes = [100, 120, 110, 90, 95, 100]
    rows = {d: (c, c, c, c) for d, c in zip(dates, closes + [100, 100])}
    o = by_h(run(rows, dates))[5]
    assert o.max_drawdown == pytest.approx(90 / 120 - 1)


# --- the calendar -----------------------------------------------------------------------------------------------------------


def test_a_holiday_week_uses_spys_dates_so_horizon_5_is_the_fifth_spy_bar():
    holiday = date(2026, 10, 12)  # SPY has no bar this Monday
    dates = sessions_after(AS_OF, 12, skip=(holiday,))
    assert dates[0] == date(2026, 10, 13)
    rows = flat(dates, 100.0, 0.001)
    rows[holiday] = (1.0, 1.0, 1.0, 1.0)  # a stray ticker bar on the closed day must be ignored
    o = by_h(run(rows, dates))[5]
    assert o.entry_date == date(2026, 10, 13) and o.exit_date == dates[5] == date(2026, 10, 20)
    assert not o.stop_hit and o.worst_move > -0.05


def test_a_half_day_is_just_a_session():
    dates = sessions_after(AS_OF, 12)
    rows = flat(dates, 100.0, 0.001)
    half = dates[2]
    rows[half] = (101.0, 101.2, 100.9, 101.1)  # a short, quiet session
    o = by_h(run(rows, dates))[5]
    assert o.status == eng.COMPLETE and o.exit_date == dates[5]


def test_the_as_of_date_is_never_the_entry_even_when_the_ticker_has_a_bar_on_it():
    dates = sessions_after(AS_OF, 8)
    rows = flat(dates)
    rows[AS_OF] = (50.0, 50.0, 50.0, 50.0)
    o = by_h(run(rows, dates))[5]
    assert o.entry_date == dates[0] and o.entry_open == pytest.approx(100.0)


# --- pending, complete, censored ------------------------------------------------------------------------------------------------


def test_nothing_after_the_as_of_date_means_every_horizon_is_pending_and_empty():
    o = run(None, [])
    assert [x.status for x in o] == [eng.PENDING] * 4 and all(x.entry_date is None and x.forward_return is None for x in o)
    o = run(flat(sessions_after(AS_OF, 3)), [])  # SPY has no bars after the as-of date either
    assert all(x.status == eng.PENDING for x in o)


def test_pending_then_complete_as_the_horizon_bar_arrives():
    dates = sessions_after(AS_OF, 11)  # horizon 10 needs the entry bar plus ten more
    rows = flat(dates, 100.0, 0.001)
    early = by_h(run({d: v for d, v in rows.items() if d <= dates[4]}, dates[:5]))
    assert early[5].status == eng.PENDING and early[5].entry_open == pytest.approx(100.0)
    assert early[5].forward_return is None and early[5].exit_date is None
    assert early[5].worst_move is not None  # the path so far is already there
    later = by_h(run(rows, dates))
    assert later[5].status == eng.COMPLETE and later[5].exit_date == dates[5] and later[10].status == eng.COMPLETE


def test_a_complete_row_does_not_change_when_more_bars_arrive():
    dates = sessions_after(AS_OF, 30)
    rows = flat(dates, 100.0, 0.001)
    short = by_h(run({d: v for d, v in rows.items() if d <= dates[6]}, dates[:7]))[5]
    full = by_h(run(rows, dates))[5]
    assert short.as_dict() == full.as_dict()


def test_a_ticker_that_stops_mid_window_is_censored_only_after_the_grace_with_the_return_to_its_last_bar():
    dates = sessions_after(AS_OF, 20)
    rows = flat(dates, 100.0, 0.001)
    rows = {d: v for d, v in rows.items() if d <= dates[7]}  # last bar is the 8th session (index 7)
    # SPY at dates[0..12]: horizon 10's date is dates[10]; 3 sessions later is dates[13] -> still inside the grace
    inside = by_h(run(rows, dates[:14]))
    assert inside[5].status == eng.COMPLETE and inside[10].status == eng.PENDING
    outside = by_h(run(rows, dates[:15]))  # more than 3 sessions past the horizon date
    cen = outside[10]
    assert cen.status == eng.CENSORED and cen.censor_reason == eng.REASON_STALE
    assert cen.exit_date == dates[7] and cen.forward_return == pytest.approx(rows[dates[7]][3] / 100.0 - 1)  # sensitivity line
    assert outside[20].status == eng.PENDING  # its own horizon is far off


def test_the_censor_reason_follows_the_ticker_status():
    dates = sessions_after(AS_OF, 20)
    rows = {d: v for d, v in flat(dates).items() if d <= dates[3]}
    assert by_h(run(rows, dates, delisted=True))[5].censor_reason == eng.REASON_DELISTED
    assert by_h(run(rows, dates, in_universe=False))[5].censor_reason == eng.REASON_LEFT_UNIVERSE
    assert by_h(run(rows, dates, delisted=True, in_universe=False))[5].censor_reason == eng.REASON_DELISTED
    assert by_h(run(rows, dates))[5].censor_reason == eng.REASON_STALE


def test_a_censored_row_still_carries_stop_benchmark_and_excess_figures():
    dates = sessions_after(AS_OF, 20)
    rows = {d: v for d, v in flat(dates).items() if d <= dates[3]}
    rows[dates[2]] = (99.0, 99.0, 85.0, 90.0)
    o = by_h(run(rows, dates, spy_drift=0.001))[5]
    assert o.status == eng.CENSORED and o.stop_hit and o.spy_return is not None and o.excess_vs_spy == pytest.approx(o.forward_return - o.spy_return)


def test_means_exclude_censored_and_pending_rows():
    dates = sessions_after(AS_OF, 20)
    complete = run(flat(dates, 100.0, 0.002), dates, spy_drift=0.0)
    censored = run({d: v for d, v in flat(dates).items() if d <= dates[3]}, dates, spy_drift=0.0)
    pending = run(flat(dates[:3]), dates[:3])
    rows = [by_h(complete)[5], by_h(censored)[5], by_h(pending)[5]]
    assert [r.status for r in rows] == [eng.COMPLETE, eng.CENSORED, eng.PENDING]
    assert eng.mean_excess(rows, 5) == pytest.approx(rows[0].excess_vs_spy)
    assert eng.mean_excess(rows[1:], 5) is None


def test_a_missing_entry_bar_is_pending_then_censored_after_the_grace():
    dates = sessions_after(AS_OF, 12)
    rows = {d: v for d, v in flat(dates).items() if d != dates[0]}  # no bar on the entry session
    early = by_h(run(rows, dates[:4]))
    assert all(x.status == eng.PENDING and x.entry_open is None for x in early.values())
    late = by_h(run(rows, dates[:9]))
    assert all(x.status == eng.CENSORED and x.forward_return is None and x.entry_open is None for x in late.values())


def test_a_ticker_with_no_bars_at_all_is_censored_once_spy_is_well_past():
    dates = sessions_after(AS_OF, 12)
    assert all(x.status == eng.PENDING for x in run(None, dates[:4]))
    assert all(x.status == eng.CENSORED for x in run(None, dates[:9], delisted=True))


# --- the entry gap ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("entry_open, flagged", [(100.0, False), (124.0, False), (126.0, True), (70.0, True), (76.0, False)])
def test_the_entry_gap_flag_fires_beyond_25_percent_either_way(entry_open, flagged):
    dates = sessions_after(AS_OF, 8)
    rows = flat(dates, entry_open)
    o = by_h(run(rows, dates, as_of_close=100.0))[5]
    assert o.entry_gap_pct == pytest.approx(entry_open / 100.0 - 1) and o.entry_gap_flag is flagged


def test_no_frozen_close_means_no_gap_figure():
    dates = sessions_after(AS_OF, 8)
    o = by_h(run(flat(dates), dates, as_of_close=None))[5]
    assert o.entry_gap_pct is None and o.entry_gap_flag is False
