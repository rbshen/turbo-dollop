"""Ticker validation at the API boundary (core/tickers.py::is_valid_ticker, core/main.py::TickerPath, core/schemas.py::TickerSymbol)."""

from datetime import datetime

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
from core.models import Watchlist, WatchlistTicker
from core.schemas import WatchlistBulkAddIn, WatchlistTickerIn, WeinsteinConfigIn
from core.tickers import is_valid_ticker, normalize_ticker, require_valid_ticker, InvalidTickerError

VALID = [
    "AAPL", "aapl", " AAPL ", "BRK-B", "BRK.B", "BF.B", "0700.HK", "MC.PA", "^GSPC", "^VIX", "SPY", "A",
    "DKKUSD", "A" * 12, "CNSWF", "9988.HK",
]
INVALID = [
    "", "   ", "A" * 13, "-A", ".A", "=1+1", "+A", "@A", "A,B", "A;B", "A B", "A\nB", "AAPL\n", "\tAAPL", "AAPL\r",
    "A/B", "A\\B", "A?B", "A#B", "A%20B", "<script>", "^^X", "A^B", "ı", "ＡＡＰＬ", "AAPL\x00", "'; DROP TABLE x;--",
]


@pytest.mark.parametrize("ticker", VALID)
def test_valid_tickers_pass(ticker):
    assert is_valid_ticker(ticker)
    assert require_valid_ticker(ticker) == ticker  # returned unchanged, never rewritten


@pytest.mark.parametrize("ticker", INVALID)
def test_invalid_tickers_fail(ticker):
    assert not is_valid_ticker(ticker)
    with pytest.raises(InvalidTickerError) as exc:
        require_valid_ticker(ticker)
    assert str(exc.value) == "Invalid ticker symbol"  # generic: the input is not echoed


def test_non_strings_fail():
    assert not is_valid_ticker(None)
    assert not is_valid_ticker(123)


def test_normalization_is_unchanged():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert normalize_ticker("0700.hk") == "0700.HK"


def test_no_valid_ticker_starts_with_a_csv_formula_character():
    for ticker in VALID:
        assert normalize_ticker(ticker)[0] not in "=+-@\t\r"


def test_every_ticker_route_validates_its_path_param():
    # A new /api/tickers/{ticker}/... or {ticker} route must take `ticker: TickerPath`.
    routes = [r for r in main.app.routes if isinstance(r, APIRoute) and "{ticker}" in r.path]
    assert len(routes) > 30
    unvalidated = []
    for route in routes:
        calls = [d.call for d in route.dependant.dependencies]
        if main._validated_ticker_path not in calls:
            unvalidated.append(f"{sorted(route.methods)} {route.path}")
    assert unvalidated == []


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/tickers/{t}/summary"),
        ("GET", "/api/tickers/{t}/step1"),
        ("GET", "/api/tickers/{t}/chart"),
        ("POST", "/api/tickers/{t}/refresh"),
        ("POST", "/api/tickers/{t}/universe"),
        ("DELETE", "/api/tickers/{t}/universe"),
        ("PUT", "/api/tickers/{t}/moat"),
        ("POST", "/api/tickers/{t}/etf-watchlist"),
        ("DELETE", "/api/watchlists/1/tickers/{t}"),
    ],
)
@pytest.mark.parametrize("bad", ["%3D1%2B1", "A%2CB", "A%0AB", "-AAPL", "A" * 40])
def test_bad_path_ticker_is_a_generic_422(monkeypatch, method, path, bad):
    _fresh_engine(monkeypatch)
    with TestClient(main.app) as client:
        response = client.request(method, path.format(t=bad), json={"moat": "Wide"} if method == "PUT" else None)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid ticker symbol"}


def test_good_path_ticker_reaches_the_handler(monkeypatch):
    _fresh_engine(monkeypatch)
    with TestClient(main.app) as client:
        assert client.get("/api/tickers/0700.HK/universe").status_code == 200
        assert client.get("/api/tickers/%5EGSPC/universe").status_code == 200
        assert client.get("/api/tickers/brk-b/universe").status_code == 200


def test_body_models_validate_tickers():
    assert WatchlistTickerIn(ticker="MC.PA").ticker == "MC.PA"
    with pytest.raises(ValidationError):
        WatchlistTickerIn(ticker="A,B")
    assert WatchlistBulkAddIn(tickers=["AAPL", "brk.b"]).tickers == ["AAPL", "brk.b"]
    with pytest.raises(ValidationError):
        WatchlistBulkAddIn(tickers=["AAPL", "=cmd|' /C calc'!A0"])
    base = dict(ma_length=30, ma_type="SMA", within_range_pct=3, slope_lookback=4, breakout_volume_mult=2,
                volume_avg_length=10, rs_smoothing_length=10)
    assert WeinsteinConfigIn(rs_benchmark="^GSPC", **base).rs_benchmark == "^GSPC"
    with pytest.raises(ValidationError):
        WeinsteinConfigIn(rs_benchmark="A B", **base)


def test_single_add_rejects_bad_ticker_and_writes_nothing(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        wl = Watchlist(name="Test", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
        session.add(wl)
        session.commit()
        wid = wl.id
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "A,B"})
    assert response.status_code == 422
    with Session(engine) as session:
        assert session.exec(select(WatchlistTicker)).all() == []


def test_bulk_add_one_invalid_item_rejects_the_whole_request(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        wl = Watchlist(name="Test", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
        session.add(wl)
        session.commit()
        wid = wl.id
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers/bulk", json={"tickers": ["AAPL", "MSFT", "=1+1"]})
    assert response.status_code == 422
    with Session(engine) as session:
        assert session.exec(select(WatchlistTicker)).all() == []
