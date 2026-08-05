from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

import pipeline.prune_cache as prune_cache
from core.models import FundamentalsCache


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(prune_cache, "engine", engine)
    monkeypatch.setattr(prune_cache, "LOG_PATH", tmp_path / "test_prune_cache.log")
    return engine


def _seed(session, ticker, statement_type, days_old):
    session.add(
        FundamentalsCache(
            ticker=ticker,
            statement_type=statement_type,
            period="annual",
            fetched_at=datetime.now() - timedelta(days=days_old),
            raw_json="[]",
        )
    )


def test_rows_older_than_retention_are_deleted(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed(session, "OLDCO", "profile", days_old=200)
        _seed(session, "FRESHCO", "profile", days_old=1)
        session.commit()

    deleted = prune_cache.prune_cache(retention_days=180)

    assert deleted == 1
    with Session(engine) as session:
        remaining = {row.ticker for row in session.exec(select(FundamentalsCache)).all()}
    assert remaining == {"FRESHCO"}


def test_dry_run_reports_but_does_not_delete(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed(session, "OLDCO", "profile", days_old=200)
        session.commit()

    deleted = prune_cache.prune_cache(retention_days=180, dry_run=True)

    assert deleted == 1
    with Session(engine) as session:
        remaining = session.exec(select(FundamentalsCache)).all()
    assert len(remaining) == 1  # nothing actually deleted


def test_nothing_to_delete_returns_zero(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed(session, "FRESHCO", "profile", days_old=1)
        session.commit()

    assert prune_cache.prune_cache(retention_days=180) == 0


def test_main_falls_back_to_settings_cache_retention_days(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(prune_cache.settings, "cache_retention_days", 30)
    captured = {}

    def fake_prune_cache(retention_days, dry_run=False):
        captured["retention_days"] = retention_days
        return 0

    monkeypatch.setattr(prune_cache, "prune_cache", fake_prune_cache)

    prune_cache.main(retention_days=None)

    assert captured["retention_days"] == 30


def test_main_explicit_retention_days_overrides_settings(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(prune_cache.settings, "cache_retention_days", 30)
    captured = {}

    def fake_prune_cache(retention_days, dry_run=False):
        captured["retention_days"] = retention_days
        return 0

    monkeypatch.setattr(prune_cache, "prune_cache", fake_prune_cache)

    prune_cache.main(retention_days=90)

    assert captured["retention_days"] == 90
