"""The ETFs screener read-model (data/etf_screener_data.py, models.py::EtfScreenerRow) and its two endpoints
GET /api/etf-screener and /api/etf-screener/meta (docs/specs/etf-screener.md). Each test builds its own
in-memory engine and patches it onto the modules that read it (the per-module convention)."""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.tracked_universe as tu
from core.models import EtfScreenerRow, FundamentalsCache, TickerView, Watchlist, WatchlistTicker
from data.etf_data import is_equity_asset_class
from data.etf_screener_data import (
    RANGE_FIELDS,
    WRITABLE_FIELDS,
    etf_screener_meta,
    list_etf_screener_rows,
    upsert_etf_screener_row,
)

NOW = datetime(2026, 11, 15, 12, 0)


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (main, tu):
        monkeypatch.setattr(module, "engine", engine)
    return engine


@pytest.fixture
def client(engine):
    return TestClient(main.app)


def _known_etf(session, ticker, viewed_days_ago=1, added=True):
    """A known ETF with a TickerView row. `added=True` (default) is the way an ETF is in the ETF universe since the
    opt-in flip; `added=False` leaves it browsed (idle <= 30 days) or expired (idle longer): out."""
    session.add(
        FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW, raw_json='{"isEtf": true}')
    )
    if viewed_days_ago is not None:
        viewed = datetime.now() - timedelta(days=viewed_days_ago)
        session.add(TickerView(ticker=ticker, last_viewed_at=viewed, added_at=viewed if added else None, added_source="user" if added else None))


# --- is_equity_asset_class ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "asset_class, expected",
    [("Equity", True), ("equity", True), (" Equity ", True), ("Fixed Income", False), ("Commodities", False),
     ("Alternatives", False), ("Multi-Asset", False), ("", False), (None, False)],
)
def test_only_the_equity_asset_class_is_equity(asset_class, expected):
    # The four live values (2026-10-02 /etf/info cache) are Equity, Fixed Income, Commodities, Alternatives.
    assert is_equity_asset_class(asset_class) is expected


# --- the table and the write helper ---------------------------------------------------------------------


def test_upsert_creates_a_partially_filled_row(engine):
    with Session(engine) as session:
        row = upsert_etf_screener_row(session, "qqq", now=NOW, name="Invesco QQQ", asset_class="Equity", expense_ratio=0.18)

    assert row.ticker == "QQQ"  # normalized
    assert (row.name, row.asset_class, row.expense_ratio) == ("Invesco QQQ", "Equity", 0.18)
    assert row.aum is None and row.beta is None and row.weinstein_stage is None  # untouched columns stay NULL
    assert row.updated_at == NOW


def test_upsert_updates_only_the_named_columns_and_stamps_updated_at(engine):
    later = NOW + timedelta(days=1)
    with Session(engine) as session:
        upsert_etf_screener_row(session, "QQQ", now=NOW, asset_class="Equity", aum=5e11, last_price=700.0)
        row = upsert_etf_screener_row(session, "QQQ", now=later, last_price=710.0, weinstein_stage="advance")

        assert row.last_price == 710.0 and row.weinstein_stage == "advance"
        assert row.asset_class == "Equity" and row.aum == 5e11  # another source's columns are not blanked
        assert row.updated_at == later
        assert len(session.exec(select(EtfScreenerRow)).all()) == 1


def test_upsert_can_set_a_column_to_none_on_purpose(engine):
    with Session(engine) as session:
        upsert_etf_screener_row(session, "QQQ", now=NOW, vs_spy_1y=3.2)
        row = upsert_etf_screener_row(session, "QQQ", now=NOW, vs_spy_1y=None)
    assert row.vs_spy_1y is None


def test_upsert_round_trips_dates_and_flags(engine):
    with Session(engine) as session:
        row = upsert_etf_screener_row(
            session,
            "SPY",
            now=NOW,
            as_of_date=date(2026, 11, 14),
            info_updated_at=datetime(2026, 11, 14, 23, 7),
            weinstein_stage_since_date=date(2026, 3, 2),
            weinstein_stage_since_is_lower_bound=False,
            bb_rsi_entry_signal=True,
            warren_active_signal_kind="blue_up",
        )
    assert row.as_of_date == date(2026, 11, 14) and row.weinstein_stage_since_date == date(2026, 3, 2)
    assert row.bb_rsi_entry_signal is True and row.warren_active_signal_kind == "blue_up"


def test_upsert_rejects_an_unknown_or_reserved_column_before_writing(engine):
    with Session(engine) as session:
        for bad in ({"market_cap": 1.0}, {"updated_at": NOW}, {"id": 1}):
            with pytest.raises(ValueError):
                upsert_etf_screener_row(session, "QQQ", **bad)
        assert session.exec(select(EtfScreenerRow)).all() == []


def test_writable_fields_are_every_value_and_bookkeeping_column_except_key_and_updated_at():
    assert "ticker" not in WRITABLE_FIELDS and "updated_at" not in WRITABLE_FIELDS
    assert {"name", "asset_class", "expense_ratio", "aum", "last_price", "pct_change_1d", "beta", "return_1y",
            "vs_spy_1y", "weinstein_stage", "as_of_date", "info_updated_at"} <= WRITABLE_FIELDS


# --- GET /api/etf-screener ------------------------------------------------------------------------------


def test_the_list_is_empty_when_no_rows_exist(client):
    assert client.get("/api/etf-screener").json() == []


def test_the_list_returns_only_rows_for_tickers_in_the_etf_universe(engine, client):
    with Session(engine) as session:
        _known_etf(session, "QQQ", viewed_days_ago=2)  # added: in
        _known_etf(session, "OLDETF", viewed_days_ago=60, added=False)  # expired: out
        _known_etf(session, "GONE", viewed_days_ago=1)
        upsert_etf_screener_row(session, "QQQ", name="Invesco QQQ", asset_class="Equity")
        upsert_etf_screener_row(session, "OLDETF", name="Old")
        upsert_etf_screener_row(session, "GONE", name="Delisted")
        upsert_etf_screener_row(session, "NOTANETF", name="Never known")  # a row for a ticker outside the universe
        upsert_etf_screener_row(session, "XLK", name="Seed with no profile row")  # a seed: in
        from core.models import TickerScore

        session.add(TickerScore(ticker="GONE", computed_at=NOW, delisted_at=NOW))
        session.commit()

    body = client.get("/api/etf-screener").json()
    assert [r["ticker"] for r in body] == ["QQQ", "XLK"]


def test_an_etf_on_a_watchlist_keeps_its_row_after_the_view_window(engine, client):
    with Session(engine) as session:
        _known_etf(session, "GLD", viewed_days_ago=400)
        watchlist = Watchlist(name="Anything", created_at=NOW, updated_at=NOW)
        session.add(watchlist)
        session.commit()
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="GLD", added_at=NOW))
        session.commit()
        upsert_etf_screener_row(session, "GLD", name="SPDR Gold Shares")

    assert [r["ticker"] for r in client.get("/api/etf-screener").json()] == ["GLD"]


def test_a_row_is_returned_with_every_field(engine, client):
    with Session(engine) as session:
        upsert_etf_screener_row(
            session, "XLK", now=NOW, name="Tech", asset_class="Equity", expense_ratio=0.08, aum=1.3e11,
            last_price=197.8, pct_change_1d=1.05, beta=1.35, return_1y=21.0, vs_spy_1y=5.6,
            weinstein_stage="advance", weinstein_stage_since_date=date(2026, 4, 6),
            as_of_date=date(2026, 11, 13),
        )
    (row,) = client.get("/api/etf-screener").json()
    assert row["expense_ratio"] == 0.08 and row["aum"] == 1.3e11 and row["vs_spy_1y"] == 5.6
    assert row["weinstein_stage"] == "advance" and row["weinstein_stage_since_date"] == "2026-04-06"
    assert row["as_of_date"] == "2026-11-13" and row["beta"] == 1.35
    assert set(row) == set(EtfScreenerRow.model_fields)


def test_beta_is_null_unless_the_fund_is_equity_and_the_stored_value_is_untouched(engine, client):
    with Session(engine) as session:
        for ticker, asset_class in (("XLK", "Equity"), ("TLT", "Fixed Income"), ("GLD", "Commodities"),
                                    ("IBIT", "Alternatives"), ("SPY", None)):
            _known_etf(session, ticker)  # XLK and SPY are seeds anyway
            upsert_etf_screener_row(session, ticker, asset_class=asset_class, beta=2.4)

    betas = {r["ticker"]: r["beta"] for r in client.get("/api/etf-screener").json()}
    assert betas == {"XLK": 2.4, "TLT": None, "GLD": None, "IBIT": None, "SPY": None}
    with Session(engine) as session:
        assert session.get(EtfScreenerRow, "TLT").beta == 2.4  # raw value stays in the table


# --- GET /api/etf-screener/meta -------------------------------------------------------------------------


def test_meta_on_an_empty_table_counts_the_seeds_and_has_null_ranges(client):
    meta = client.get("/api/etf-screener/meta").json()
    assert meta["total_etfs"] == len(tu.ETF_SEED_TICKERS) and meta["row_count"] == 0
    assert "hidden_inactive" not in meta and meta["asset_classes"] == []
    assert set(meta["ranges"]) == set(RANGE_FIELDS)
    assert all(r == {"min": None, "max": None} for r in meta["ranges"].values())


def test_meta_reports_counts_asset_classes_and_ranges(engine, client):
    with Session(engine) as session:
        _known_etf(session, "QQQ", 1)
        _known_etf(session, "TLT", 1)
        _known_etf(session, "OLD1", 90, added=False)
        _known_etf(session, "OLD2", 90, added=False)
        upsert_etf_screener_row(session, "QQQ", asset_class="Equity", expense_ratio=0.18, aum=5e11, beta=1.2,
                                last_price=700.0, pct_change_1d=-0.5, return_1y=23.0, vs_spy_1y=7.6)
        upsert_etf_screener_row(session, "TLT", asset_class="Fixed Income", expense_ratio=0.15, aum=4.6e10, beta=2.4,
                                last_price=77.7, pct_change_1d=0.2, return_1y=-4.0, vs_spy_1y=-19.0)
        upsert_etf_screener_row(session, "OLD1", asset_class="Commodities", expense_ratio=9.0, aum=1.0)  # hidden: not counted

    meta = client.get("/api/etf-screener/meta").json()
    assert meta["total_etfs"] == len(tu.ETF_SEED_TICKERS) + 2  # + QQQ, TLT; the two expired (unadded) ETFs are not in
    assert meta["row_count"] == 2
    assert "hidden_inactive" not in meta  # removed with the opt-in flip
    assert meta["asset_classes"] == ["Equity", "Fixed Income"]
    r = meta["ranges"]
    assert r["expense_ratio"] == {"min": 0.15, "max": 0.18}
    assert r["aum"] == {"min": 4.6e10, "max": 5e11}
    assert r["beta"] == {"min": 1.2, "max": 1.2}  # TLT's 2.4 is nulled by the equity-only rule, so not in the range
    assert r["vs_spy_1y"] == {"min": -19.0, "max": 7.6}
    assert r["pct_change_1d"] == {"min": -0.5, "max": 0.2}


def test_meta_helper_matches_the_endpoint(engine):
    with Session(engine) as session:
        upsert_etf_screener_row(session, "XLK", asset_class="Equity", last_price=100.0)
        assert etf_screener_meta(session).row_count == len(list_etf_screener_rows(session)) == 1


# --- routing --------------------------------------------------------------------------------------------


def test_the_etf_endpoints_do_not_sit_under_the_stock_screener_prefix():
    paths = {route.path for route in main.app.routes}
    assert {"/api/etf-screener", "/api/etf-screener/meta"} <= paths
    assert not any(p.startswith("/api/etf-screener") and p.startswith("/api/screener") for p in paths)
    # The existing stock endpoints are where they were.
    assert {"/api/screener", "/api/screener/meta", "/api/screener/recompute", "/api/screener/filters"} <= paths
