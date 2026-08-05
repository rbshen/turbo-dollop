from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

import pipeline.nightly_fundamentals_fetch as nightly
import pipeline.stale_data_health_check as health_check
from core.models import FundamentalsCache, IndexConstituent


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(health_check, "engine", engine)
    monkeypatch.setattr(nightly, "engine", engine)
    monkeypatch.setattr(health_check, "LOG_PATH", tmp_path / "test_stale.log")
    return engine


def _seed_profile(session, ticker, days_old):
    session.add(
        FundamentalsCache(
            ticker=ticker,
            statement_type="profile",
            period="annual",
            fetched_at=datetime.now() - timedelta(days=days_old),
            raw_json="[]",
        )
    )


def test_fresh_stale_and_never_fetched_are_classified_correctly(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "FRESHCO", days_old=1)
        _seed_profile(session, "STALECO", days_old=20)
        session.commit()

    result = health_check.check_staleness(["FRESHCO", "STALECO", "NEVERCO"], threshold_days=10)

    assert result["fresh"] == ["FRESHCO"]
    assert result["stale"] == [("STALECO", 20)]
    assert result["never_fetched"] == ["NEVERCO"]


def test_threshold_boundary_is_exclusive_of_the_threshold_itself(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "EXACTLYCO", days_old=10)
        session.commit()

    result = health_check.check_staleness(["EXACTLYCO"], threshold_days=10)

    assert result["fresh"] == ["EXACTLYCO"]  # days_old == threshold is not > threshold


def test_report_formatting_lists_stale_and_never_fetched_tickers():
    result = {"fresh": ["A"], "stale": [("B", 15), ("C", 30)], "never_fetched": ["D"]}

    report = health_check._format_report(result, total=4, threshold_days=10)

    assert "Fresh:         1" in report
    assert "Stale:         2" in report
    assert "Never fetched: 1" in report
    assert "C: 30d" in report and "B: 15d" in report
    assert "D" in report


def test_main_uses_the_universe_ticker_list_and_writes_a_report(monkeypatch, tmp_path, capsys):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        _seed_profile(session, "AAPL", days_old=1)
        session.commit()

    result = health_check.main(threshold_days=10)

    assert result["fresh"] == ["AAPL"]
    captured = capsys.readouterr()
    assert "Stale-data health check (1 tickers" in captured.out
