"""Neutralisation in the watchlist export files (data/export_safety.py, GET /api/watchlists/{id}/export/thinkorswim)."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
from core.models import Watchlist, WatchlistTicker
from data.export_safety import neutralise_csv_symbol, thinkorswim_csv


@pytest.mark.parametrize("raw", ["BRK-B", "^GSPC", "^VIX", "0700.HK", "MC.PA", "AAPL", "A-B-C"])
def test_legitimate_symbols_export_unchanged(raw):
    assert neutralise_csv_symbol(raw) == raw


@pytest.mark.parametrize("raw", ["=1+1", "+A", "-A", "@SUM(A1)", "=cmd|' /C calc'!A0"])
def test_leading_formula_character_is_defused(raw):
    out = neutralise_csv_symbol(raw)
    assert out.startswith("'") and out[1] == raw[0]


def test_leading_whitespace_cannot_hide_a_formula_character():
    assert neutralise_csv_symbol("\t=A") == "'=A"
    assert neutralise_csv_symbol("\r=A") == "'=A"
    assert neutralise_csv_symbol(" +A") == "'+A"


def test_symbol_cannot_split_a_row():
    assert neutralise_csv_symbol("AAPL\r\nMSFT") == "AAPLMSFT"
    assert neutralise_csv_symbol("AAPL\nMSFT") == "AAPLMSFT"
    assert neutralise_csv_symbol("AAPL MSFT") == "AAPLMSFT"
    assert neutralise_csv_symbol("A,B") == "AB"
    assert neutralise_csv_symbol('A"B') == "AB"
    out = thinkorswim_csv(["AAPL\nMSFT", "GOOG\r=1+1"])
    assert out.count("\n") == 2 and "\r" not in out
    assert out == "AAPLMSFT\n'GOOG=1+1\n".replace("'GOOG", "GOOG")  # the formula character is mid-line, not leading


def test_empty_after_cleaning_is_left_out():
    assert thinkorswim_csv(["", " ", "\n", "AAPL"]) == "AAPL\n"
    assert thinkorswim_csv([]) == ""


def test_thinkorswim_endpoint_neutralises_stored_rows(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    now = datetime(2026, 1, 1)
    with Session(engine) as session:
        wl = Watchlist(name="Test", created_at=now, updated_at=now)
        session.add(wl)
        session.commit()
        # Rows that predate the validator (written straight to the DB).
        for t in ["BRK-B", "^GSPC", "=1+1", "AAPL\nMSFT", "@x"]:
            session.add(WatchlistTicker(watchlist_id=wl.id, ticker=t, added_at=now))
        session.commit()
        wid = wl.id
    with TestClient(main.app) as client:
        response = client.get(f"/api/watchlists/{wid}/export/thinkorswim")
    assert response.status_code == 200
    assert response.text == "BRK-B\n^GSPC\n'=1+1\nAAPLMSFT\n'@x\n"
