"""pipeline/cache_history_audit.py is read-only: it reports periods held and the oldest period per cache key, and
refuses to write (the CLI opens the file with SQLite mode=ro)."""

import json
from datetime import date, datetime

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

from core.models import CorporateEvent, FundamentalsCache, LongHistoryBars, SharedBarsCache
from pipeline.cache_history_audit import build_audit, format_audit, read_only_engine


def _rows(first: int, last: int) -> list[dict]:
    return [{"date": f"{y}-12-31"} for y in range(last, first - 1, -1)]


def _seed(session):
    for ticker, rows in (("AAA", _rows(2016, 2025)), ("BBB", _rows(2016, 2025)), ("CCC", _rows(2021, 2025)), ("DDD", [])):
        session.add(FundamentalsCache(ticker=ticker, statement_type="income_statement", period="annual", fetched_at=datetime.now(), raw_json=json.dumps(rows)))
    session.add(FundamentalsCache(ticker="AAA", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="[]"))
    for d in (datetime(2021, 10, 4), datetime(2026, 9, 30)):
        session.add(SharedBarsCache(ticker="AAA", interval="1d", bar_time=d, open=1, high=1, low=1, close=1, volume=1, fetched_at=datetime.now()))
        session.add(LongHistoryBars(ticker="AAA", bar_time=d, open=1, high=1, low=1, close=1, volume=1, fetched_at=datetime.now()))
    session.add(CorporateEvent(ticker="AAA", event_type="earnings", event_date=date(2023, 1, 5)))
    session.commit()


def test_audit_counts_tickers_per_number_of_periods_and_the_oldest_period():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session)
        audit = build_audit(session)
    entry = audit["fundamentals"]["income_statement/annual"]
    assert entry["tickers"] == 4 and entry["periods_held"] == {"10": 2, "5": 1, "0": 1}
    assert entry["oldest_period"] == {"min": "2016-12-31", "median": "2016-12-31", "max": "2021-12-31"}
    assert entry["tickers_by_oldest_year"] == {"2016": 2, "2021": 1}
    assert "profile/latest" not in audit["fundamentals"]  # snapshots are not history
    assert audit["bars"]["shared_bars_cache/1d"]["span_years"]["max"] == 4.99
    assert audit["bars"]["long_history_bars"]["tickers"] == 1
    assert audit["events"]["corporate_event/earnings"]["tickers"] == 1
    text = format_audit(audit)
    assert "income_statement/annual" in text and "10p x2" in text


def test_the_cli_engine_cannot_write(tmp_path):
    path = tmp_path / "copy.db"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session)
    ro = read_only_engine(path)
    with Session(ro) as session:
        assert build_audit(session)["fundamentals"]  # reads fine
        with pytest.raises(OperationalError):
            session.add(FundamentalsCache(ticker="X", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="[]"))
            session.commit()
