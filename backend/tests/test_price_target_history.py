from datetime import date

from helpers.price_target_history import reconstruct_monthly_snapshots


def _news_row(analyst: str, published: str, target: float) -> dict:
    return {"analystCompany": analyst, "publishedDate": published, "priceTarget": target}


def test_empty_input_returns_empty_list():
    assert reconstruct_monthly_snapshots([]) == []


def test_missing_required_fields_returns_empty_list():
    assert reconstruct_monthly_snapshots([{"symbol": "TEST"}]) == []


def test_rows_with_blank_analyst_or_missing_target_are_dropped():
    rows = [
        _news_row("", "2024-01-05T00:00:00.000Z", 100),
        {"analystCompany": "Firm A", "publishedDate": "2024-01-05T00:00:00.000Z", "priceTarget": None},
    ]
    assert reconstruct_monthly_snapshots(rows, before=date(2024, 3, 1)) == []


def test_single_analyst_single_target_holds_flat_across_months():
    rows = [_news_row("Firm A", "2024-01-05T00:00:00.000Z", 100.0)]
    result = reconstruct_monthly_snapshots(rows, before=date(2024, 4, 1))

    assert [r["snapshot_date"] for r in result] == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)]
    for row in result:
        assert row["target_consensus"] == 100.0
        assert row["target_high"] == 100.0
        assert row["target_low"] == 100.0
        assert row["target_median"] == 100.0


def test_rolling_most_recent_per_analyst_averages_across_active_analysts():
    # Firm A starts at 100 in Jan, raised to 120 in March.
    # Firm B only starts covering in Feb at 200 -- must not count in Jan's average.
    rows = [
        _news_row("Firm A", "2024-01-10T00:00:00.000Z", 100.0),
        _news_row("Firm B", "2024-02-10T00:00:00.000Z", 200.0),
        _news_row("Firm A", "2024-03-10T00:00:00.000Z", 120.0),
    ]
    result = reconstruct_monthly_snapshots(rows, before=date(2024, 4, 1))
    by_date = {r["snapshot_date"]: r for r in result}

    jan = by_date[date(2024, 1, 31)]
    assert jan["target_consensus"] == 100.0
    assert jan["target_high"] == 100.0
    assert jan["target_low"] == 100.0

    feb = by_date[date(2024, 2, 29)]
    assert feb["target_consensus"] == 150.0  # mean(100, 200)
    assert feb["target_high"] == 200.0
    assert feb["target_low"] == 100.0
    assert feb["target_median"] == 150.0

    mar = by_date[date(2024, 3, 31)]
    assert mar["target_consensus"] == 160.0  # mean(120, 200) -- Firm A's stale 100 is replaced, not averaged in twice
    assert mar["target_low"] == 120.0
    assert mar["target_high"] == 200.0


def test_same_analyst_multiple_actions_same_day_keeps_the_last_one():
    rows = [
        _news_row("Firm A", "2024-01-10T09:00:00.000Z", 90.0),
        _news_row("Firm A", "2024-01-10T15:00:00.000Z", 110.0),
    ]
    result = reconstruct_monthly_snapshots(rows, before=date(2024, 2, 1))
    assert result[0]["target_consensus"] == 110.0


def test_before_cutoff_excludes_the_cutoff_months_own_month_and_later():
    rows = [_news_row("Firm A", "2024-01-05T00:00:00.000Z", 100.0)]
    # before= a date IN March -> last full month is February, March itself excluded.
    result = reconstruct_monthly_snapshots(rows, before=date(2024, 3, 15))
    assert [r["snapshot_date"] for r in result] == [date(2024, 1, 31), date(2024, 2, 29)]


def test_before_on_or_before_earliest_reconstructable_month_yields_nothing():
    # Simulates re-running the backfill against a ticker it has already
    # fully processed -- `before` is the earliest already-stored snapshot,
    # which sits at or before what this data could reconstruct anyway.
    rows = [_news_row("Firm A", "2024-03-05T00:00:00.000Z", 100.0)]
    assert reconstruct_monthly_snapshots(rows, before=date(2024, 3, 31)) == []
    assert reconstruct_monthly_snapshots(rows, before=date(2024, 2, 1)) == []


def test_none_before_stops_at_the_last_full_month_before_today():
    rows = [_news_row("Firm A", "2024-01-05T00:00:00.000Z", 100.0)]
    result = reconstruct_monthly_snapshots(rows, before=None)
    last = result[-1]["snapshot_date"]
    # The current in-progress month must never be included.
    assert last < date.today().replace(day=1)
    assert last.day in (28, 29, 30, 31)  # always a real month-end
