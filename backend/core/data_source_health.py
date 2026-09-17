"""Records the timestamp of the most recent genuinely successful live call
to each external data source -- the write side of the Settings "Status"
section's Data Sources cards (see core/data_source_status.py for the read
side / health computation).

Mirrors core/cron_health.py's own conventions on purpose: its own module-
level `engine` reference (so a test can monkeypatch this module's engine
independently, the established per-module engine-isolation convention --
see CLAUDE.md's "Ad-hoc reproduction scripts must not touch the real
database"), a defensive `create_all` on every call (this module has no
guaranteed init_db() call before it, since it's invoked from deep inside
clients/fmp_client.py and clients/yahoo_client.py, which are reached from
both the FastAPI app and cron scripts alike), and every write wrapped in
try/except-and-swallow -- a health-tracking write failing must never break
the real fetch it's piggybacking on, the same reasoning cron_heartbeat's
own docstring gives for its own swallowed writes.

Test isolation for this module's `engine` is handled once, globally, in
tests/conftest.py -- not per test file -- since FMPClient.get and
YahooClient.get_history (the two call sites) are exercised for real (not
just monkeypatched away) by test_fmp_client.py/test_yahoo_client.py."""

from datetime import datetime

from sqlmodel import Session, SQLModel

from core.db import engine
from core.models import DataSourceHealth


def record_success(source: str) -> None:
    try:
        SQLModel.metadata.create_all(engine, tables=[DataSourceHealth.__table__])
        with Session(engine) as session:
            row = session.get(DataSourceHealth, source)
            now = datetime.now()
            if row is None:
                session.add(DataSourceHealth(source=source, last_success_at=now))
            else:
                row.last_success_at = now
                session.add(row)
            session.commit()
    except Exception:
        pass
