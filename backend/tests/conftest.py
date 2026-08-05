"""Session-scoped safety net: fails loudly, immediately, if any test writes
to the REAL `core.db.engine` instead of a properly-isolated in-memory test
engine -- the exact root cause of the PEP/ACME fixture-contamination
incidents (see CLAUDE.md's "Ad-hoc reproduction scripts must not touch the
real database"). A missing `monkeypatch.setattr(some_module, "engine",
test_engine)` now surfaces as an immediate, loud test failure with a clear
message, instead of a silent write that can sit undetected in production
for days.

Hooks the database driver itself (`before_cursor_execute`), not
`cache.get_or_fetch` specifically -- this catches every write path,
including ones this comment can't anticipate, not just the one call site
the original incidents happened to go through.

Registered once, for the pytest process's entire lifetime, via a
session-scoped autouse fixture. This never affects the real app: a normal
interactive run or a cron job never imports pytest and never constructs
this fixture, so `core.db.engine` never gets this listener attached
outside of a pytest session."""

import pytest
from sqlalchemy import event

from core.db import engine as real_engine

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "REPLACE")


def _forbid_write(conn, cursor, statement, parameters, context, executemany):
    normalized = statement.strip().upper()
    if normalized.startswith(_WRITE_PREFIXES):
        raise RuntimeError(
            "A test attempted to write to the REAL core.db.engine "
            f"(statement: {statement[:200]!r}). Some module's `engine` "
            "reference is missing its monkeypatch -- see CLAUDE.md's "
            '"Ad-hoc reproduction scripts must not touch the real '
            'database" for the incident this guards against.'
        )


@pytest.fixture(autouse=True, scope="session")
def _forbid_writes_to_real_db():
    event.listen(real_engine, "before_cursor_execute", _forbid_write)
    yield
    event.remove(real_engine, "before_cursor_execute", _forbid_write)
