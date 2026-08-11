from datetime import date, datetime

from sqlmodel import Session, SQLModel, create_engine, select

import pipeline.merge_duplicate_ticker_identities as merge
from core.models import (
    FundamentalsCache,
    IndexConstituent,
    PriceTargetSnapshot,
    TickerMoat,
    TickerScore,
    Watchlist,
    WatchlistTicker,
)


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(merge, "engine", engine)
    monkeypatch.setattr(merge, "LOG_PATH", tmp_path / "test_merge_duplicate_ticker_identities.log")
    return engine


def test_single_row_table_renames_when_canonical_absent(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerMoat(ticker="BF.B", moat="wide_moat", updated_at=datetime(2026, 8, 9)))
        session.commit()

    changes = merge.merge_duplicate_ticker_identities()

    assert len(changes) == 1
    with Session(engine) as session:
        rows = session.exec(select(TickerMoat)).all()
    assert [(r.ticker, r.moat) for r in rows] == [("BF-B", "wide_moat")]


def test_single_row_table_conflict_dot_form_fresher_wins(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerMoat(ticker="BRK-B", moat="no_moat", updated_at=datetime(2026, 8, 8, 22)))
        session.add(TickerMoat(ticker="BRK.B", moat="narrow_moat", updated_at=datetime(2026, 8, 8, 23)))
        session.commit()

    merge.merge_duplicate_ticker_identities()

    with Session(engine) as session:
        rows = session.exec(select(TickerMoat)).all()
    # Dot-form row was fresher -- its data (narrow_moat) survives under the
    # canonical hyphen ticker; the stale hyphen row is gone entirely.
    assert [(r.ticker, r.moat) for r in rows] == [("BRK-B", "narrow_moat")]


def test_single_row_table_conflict_canonical_fresher_wins(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerMoat(ticker="BRK-B", moat="narrow_moat", updated_at=datetime(2026, 8, 9)))
        session.add(TickerMoat(ticker="BRK.B", moat="no_moat", updated_at=datetime(2026, 8, 6)))
        session.commit()

    merge.merge_duplicate_ticker_identities()

    with Session(engine) as session:
        rows = session.exec(select(TickerMoat)).all()
    assert [(r.ticker, r.moat) for r in rows] == [("BRK-B", "narrow_moat")]


def test_fundamentals_cache_resolves_each_statement_type_independently(monkeypatch, tmp_path):
    # Mirrors the real live-DB state this script was built to fix: BRK.B and
    # BRK-B disagreed on which was fresher per statement_type, not
    # uniformly -- each (statement_type, period) group must resolve on its
    # own freshness, not a single ticker-level comparison.
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="BRK.B", statement_type="profile", period="latest", fetched_at=datetime(2026, 8, 6), raw_json="{}"))
        session.add(FundamentalsCache(ticker="BRK-B", statement_type="profile", period="latest", fetched_at=datetime(2026, 8, 8), raw_json="{}"))
        session.add(FundamentalsCache(ticker="BRK.B", statement_type="quote", period="latest", fetched_at=datetime(2026, 8, 10), raw_json="{}"))
        session.add(FundamentalsCache(ticker="BRK-B", statement_type="quote", period="latest", fetched_at=datetime(2026, 8, 9), raw_json="{}"))
        session.commit()

    merge.merge_duplicate_ticker_identities()

    with Session(engine) as session:
        rows = session.exec(select(FundamentalsCache)).all()
    by_type = {r.statement_type: (r.ticker, r.fetched_at) for r in rows}
    assert len(rows) == 2
    assert by_type["profile"] == ("BRK-B", datetime(2026, 8, 8))  # hyphen was fresher here
    assert by_type["quote"] == ("BRK-B", datetime(2026, 8, 10))  # dot was fresher here, renamed to canonical


def test_watchlist_ticker_both_shapes(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        wl_dot_only = Watchlist(name="DotOnly", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
        wl_both = Watchlist(name="Both", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
        session.add(wl_dot_only)
        session.add(wl_both)
        session.commit()
        session.refresh(wl_dot_only)
        session.refresh(wl_both)

        session.add(WatchlistTicker(watchlist_id=wl_dot_only.id, ticker="BRK.B", added_at=datetime(2026, 1, 1)))
        session.add(WatchlistTicker(watchlist_id=wl_both.id, ticker="BRK-B", added_at=datetime(2026, 1, 1)))
        session.add(WatchlistTicker(watchlist_id=wl_both.id, ticker="BRK.B", added_at=datetime(2026, 1, 2)))
        session.commit()
        dot_only_id, both_id = wl_dot_only.id, wl_both.id

    merge.merge_duplicate_ticker_identities()

    with Session(engine) as session:
        dot_only_tickers = [t.ticker for t in session.exec(select(WatchlistTicker).where(WatchlistTicker.watchlist_id == dot_only_id)).all()]
        both_tickers = [t.ticker for t in session.exec(select(WatchlistTicker).where(WatchlistTicker.watchlist_id == both_id)).all()]

    assert dot_only_tickers == ["BRK-B"]  # renamed in place, no conflict
    assert both_tickers == ["BRK-B"]  # dot-form duplicate simply removed


def test_index_constituent_clean_rename(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="BRK.B", company_name="Berkshire Hathaway", last_synced_at=datetime(2026, 8, 1)))
        session.commit()

    merge.merge_duplicate_ticker_identities()

    with Session(engine) as session:
        rows = session.exec(select(IndexConstituent)).all()
    assert [(r.index_name, r.ticker) for r in rows] == [("sp500", "BRK-B")]


def test_price_target_snapshot_append_only_freshness_wins(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        # Distinct months for both tickers -- no collision, both survive
        # renamed to canonical.
        session.add(PriceTargetSnapshot(ticker="BRK.B", snapshot_date=date(2026, 6, 1), fetched_at=datetime(2026, 6, 1)))
        session.add(PriceTargetSnapshot(ticker="BRK-B", snapshot_date=date(2026, 7, 1), fetched_at=datetime(2026, 7, 1)))
        # Same month for both -- a real collision, freshest fetched_at wins.
        session.add(PriceTargetSnapshot(ticker="BRK.B", snapshot_date=date(2026, 8, 1), target_consensus=300.0, fetched_at=datetime(2026, 8, 5)))
        session.add(PriceTargetSnapshot(ticker="BRK-B", snapshot_date=date(2026, 8, 1), target_consensus=310.0, fetched_at=datetime(2026, 8, 6)))
        session.commit()

    merge.merge_duplicate_ticker_identities()

    with Session(engine) as session:
        rows = session.exec(select(PriceTargetSnapshot).order_by(PriceTargetSnapshot.snapshot_date)).all()
    assert [(r.snapshot_date, r.ticker, r.target_consensus) for r in rows] == [
        (date(2026, 6, 1), "BRK-B", None),
        (date(2026, 7, 1), "BRK-B", None),
        (date(2026, 8, 1), "BRK-B", 310.0),  # fresher fetched_at (08-06) wins over 08-05
    ]


def test_idempotent_second_run_makes_no_changes(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerMoat(ticker="BRK.B", moat="narrow_moat", updated_at=datetime(2026, 8, 9)))
        session.commit()

    first = merge.merge_duplicate_ticker_identities()
    second = merge.merge_duplicate_ticker_identities()

    assert len(first) == 1
    assert second == []


def test_non_aliased_ticker_is_never_touched(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL", company_name="Apple Inc.", computed_at=datetime(2026, 8, 8)))
        session.add(TickerMoat(ticker="AAPL", moat="wide_moat", updated_at=datetime(2026, 8, 8)))
        session.add(FundamentalsCache(ticker="AAPL", statement_type="profile", period="latest", fetched_at=datetime(2026, 8, 8), raw_json="{}"))
        session.commit()

    changes = merge.merge_duplicate_ticker_identities()

    assert changes == []
    with Session(engine) as session:
        assert session.exec(select(TickerScore)).all()[0].ticker == "AAPL"
        assert session.exec(select(TickerMoat)).all()[0].ticker == "AAPL"
        assert session.exec(select(FundamentalsCache)).all()[0].ticker == "AAPL"


def test_dry_run_reports_but_does_not_change(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(TickerMoat(ticker="BF.B", moat="wide_moat", updated_at=datetime(2026, 8, 9)))
        session.commit()

    changes = merge.merge_duplicate_ticker_identities(dry_run=True)

    assert len(changes) == 1
    with Session(engine) as session:
        rows = session.exec(select(TickerMoat)).all()
    assert [r.ticker for r in rows] == ["BF.B"]  # nothing actually changed


def test_main_falls_back_gracefully_when_nothing_to_merge(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    changes = merge.main()

    assert changes == []
