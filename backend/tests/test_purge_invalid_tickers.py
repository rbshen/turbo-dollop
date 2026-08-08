from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

import pipeline.purge_invalid_tickers as purge
from core.models import FundamentalsCache, IndexConstituent, TickerScore


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(purge, "engine", engine)
    monkeypatch.setattr(purge, "LOG_PATH", tmp_path / "test_purge_invalid_tickers.log")
    return engine


def _seed_profile(session, ticker, company_name):
    # FMP's real "no such symbol" shape is an empty list, not a dict
    # without the field -- mirror that here rather than {} for realism.
    raw = "[]" if company_name is None else f'[{{"companyName": "{company_name}", "symbol": "{ticker}"}}]'
    session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json=raw))


def test_ticker_with_confirmed_empty_profile_is_purged(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "POOLL", company_name=None)
        session.add(
            FundamentalsCache(
                ticker="POOLL", statement_type="income_statement", period="annual", fetched_at=datetime.now(), raw_json="[]"
            )
        )
        session.commit()

    purged = purge.purge_invalid_tickers()

    assert purged == ["POOLL"]
    with Session(engine) as session:
        remaining = session.exec(select(FundamentalsCache)).all()
    assert remaining == []  # every statement_type for the ticker is removed, not just profile


def test_ticker_with_real_company_name_is_kept(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "AAPL", company_name="Apple Inc.")
        session.commit()

    purged = purge.purge_invalid_tickers()

    assert purged == []
    with Session(engine) as session:
        remaining = {row.ticker for row in session.exec(select(FundamentalsCache)).all()}
    assert remaining == {"AAPL"}


def test_index_member_is_never_purged_even_with_an_empty_profile(monkeypatch, tmp_path):
    # Defense-in-depth case: shouldn't happen in practice, but a real index
    # constituent must never be deleted just because check 2 matched.
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="WEIRD", company_name="Weird Co", last_synced_at=datetime.now()))
        _seed_profile(session, "WEIRD", company_name=None)
        session.commit()

    purged = purge.purge_invalid_tickers()

    assert purged == []
    with Session(engine) as session:
        remaining = {row.ticker for row in session.exec(select(FundamentalsCache)).all()}
    assert remaining == {"WEIRD"}


def test_ticker_with_no_profile_row_at_all_is_ambiguous_and_kept(monkeypatch, tmp_path):
    # No profile row means "never attempted" or "attempted and failed/
    # paywalled" -- indistinguishable from a genuinely invalid symbol, so
    # this must never be purged (e.g. DXC's real-world shape).
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker="DXC", statement_type="analyst_estimates", period="latest", fetched_at=datetime.now(), raw_json="[]"
            )
        )
        session.commit()

    purged = purge.purge_invalid_tickers()

    assert purged == []
    with Session(engine) as session:
        remaining = {row.ticker for row in session.exec(select(FundamentalsCache)).all()}
    assert remaining == {"DXC"}


def test_dry_run_reports_but_does_not_delete(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "POOLL", company_name=None)
        session.commit()

    purged = purge.purge_invalid_tickers(dry_run=True)

    assert purged == ["POOLL"]
    with Session(engine) as session:
        remaining = session.exec(select(FundamentalsCache)).all()
    assert len(remaining) == 1  # nothing actually deleted


def test_any_leftover_ticker_score_row_is_also_removed(monkeypatch, tmp_path):
    # Structurally shouldn't exist (compute_ticker_score refuses to write a
    # row when company_name is None) -- deleted defensively anyway, not
    # assumed impossible.
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "POOLL", company_name=None)
        session.add(TickerScore(ticker="POOLL", overall_score=None, computed_at=datetime.now()))
        session.commit()

    purge.purge_invalid_tickers()

    with Session(engine) as session:
        remaining = session.exec(select(TickerScore)).all()
    assert remaining == []


def test_multiple_tickers_in_one_run(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        _seed_profile(session, "POOLL", company_name=None)
        _seed_profile(session, "PEPSI", company_name=None)
        _seed_profile(session, "AAPL", company_name="Apple Inc.")
        session.commit()

    purged = purge.purge_invalid_tickers()

    assert purged == ["PEPSI", "POOLL"]


def test_main_falls_back_gracefully_when_nothing_to_purge(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    purged = purge.main()

    assert purged == []
