"""Regression test for conftest.py's _forbid_writes_to_real_db fixture --
confirms the guard actually fires on a real write attempt against the real
core.db.engine, rather than trusting the fixture is wired correctly on
faith. Does not (and must not) actually commit anything: the guard raises
before the statement reaches SQLite."""

from datetime import datetime

import pytest
from sqlmodel import Session

from core.db import engine
from core.models import GrowthCatalystNote


def test_write_guard_fires_on_a_real_write_attempt():
    with Session(engine) as session:
        session.add(
            GrowthCatalystNote(ticker="__WRITE_GUARD_TEST__", notes="should never persist", updated_at=datetime.now())
        )
        with pytest.raises(RuntimeError, match="attempted to write to the REAL core.db.engine"):
            session.commit()
    # Confirm nothing was actually written despite the attempt.
    with Session(engine) as verify_session:
        assert verify_session.get(GrowthCatalystNote, "__WRITE_GUARD_TEST__") is None


def test_write_guard_does_not_block_reads():
    with Session(engine) as session:
        # A plain SELECT against the real engine must not raise -- the
        # guard only blocks writes, never reads.
        session.get(GrowthCatalystNote, "AAPL")
