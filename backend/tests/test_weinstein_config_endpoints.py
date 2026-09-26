from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
from analysis.trend_structure.weinstein import WeinsteinParams
from helpers.weinstein_config import load_weinstein_params

_VALID_BODY = {
    "ma_length": 26,
    "ma_type": "SMA",
    "within_range_pct": 4.5,
    "slope_lookback": 4,
    "breakout_volume_mult": 1.5,
    "volume_avg_length": 40,
    "rs_benchmark": "qqq",
    "rs_smoothing_length": 40,
}


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_get_returns_lazily_seeded_defaults_matching_the_engine_defaults(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    body = TestClient(main.app).get("/api/config/weinstein").json()

    d = WeinsteinParams()
    assert (body["ma_length"], body["ma_type"], body["within_range_pct"], body["slope_lookback"]) == (30, "EMA", 5.0, 5)
    assert (body["breakout_volume_mult"], body["volume_avg_length"], body["rs_benchmark"], body["rs_smoothing_length"]) == (2.0, 50, "SPY", 52)
    with Session(engine) as session:
        assert load_weinstein_params(session) == d


def test_put_persists_and_the_engine_reads_it_live(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    put = client.put("/api/config/weinstein", json=_VALID_BODY)
    assert put.status_code == 200
    assert put.json()["rs_benchmark"] == "QQQ"  # normalized

    with Session(engine) as session:
        params = load_weinstein_params(session)  # a fresh read, no process-level cache
    assert (params.ma_type, params.ma_length, params.within_range_pct, params.rs_benchmark) == ("SMA", 26, 4.5, "QQQ")


def test_put_rejects_invalid_values(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)
    for bad in (
        {"ma_type": "WMA"},
        {"ma_length": 1},
        {"slope_lookback": 0},
        {"within_range_pct": -1},
        {"breakout_volume_mult": 0},
        {"volume_avg_length": 1},
        {"rs_benchmark": ""},
        {"rs_smoothing_length": 1},
    ):
        assert client.put("/api/config/weinstein", json={**_VALID_BODY, **bad}).status_code == 422, bad
