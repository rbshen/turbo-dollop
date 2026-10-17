"""Root conftest: points the whole test process at a throwaway database file BEFORE any application module is imported.

`core.db` builds `engine` once, at import, from `settings.database_path`, and 82 production modules bind it with
`from core.db import engine`, so no fixture can redirect them afterwards (a per-test `monkeypatch` only reaches the modules
it names). Setting `DATABASE_PATH` here (an environment variable beats `backend/.env`) makes every one of those modules bind
a temp-file engine from the start: the real `backend/fathom.db` is never opened by a test, whatever module a test reaches
and whether or not it patched that module's `engine`. A read of an unpatched module sees an empty, schema-complete database
(deterministic), and a write is still refused by the session write guard in `tests/conftest.py`.

This file sits at `backend/` (not `backend/tests/`) because `testpaths` also covers `scoring/` and `analysis/`, which do not
load `tests/conftest.py`. Nothing here changes production code. Convention: docs/decisions.md, 2026-10-17."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="fathom-test-db-"))
_TEST_DB_PATH = _TEST_DB_DIR / "fathom-test.db"
atexit.register(shutil.rmtree, _TEST_DB_DIR, ignore_errors=True)

# Too late once the settings or the engine exist: they would already point at the real file. Fail loudly rather than test against it.
_already = [name for name in ("core.config", "core.db") if name in sys.modules]
if _already:
    raise RuntimeError(
        f"{', '.join(_already)} was imported before backend/conftest.py ran, so the test database cannot be redirected and "
        "tests would read the REAL fathom.db. Something (a -p plugin, a conftest above backend/) imports the app too early."
    )

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)

from sqlmodel import SQLModel  # noqa: E402

import core.db as _db  # noqa: E402
from core.config import BASE_DIR  # noqa: E402

# Import-time assertion: the engine every module binds is the throwaway one, never the real file.
_real_path = (BASE_DIR / "fathom.db").resolve()
if _db.DB_PATH == _real_path or _db.DB_PATH != _TEST_DB_PATH.resolve() or Path(str(_db.engine.url.database)).resolve() != _TEST_DB_PATH.resolve():
    raise RuntimeError(
        f"The test engine points at {_db.engine.url.database!r} (DB_PATH {_db.DB_PATH}), not the throwaway {_TEST_DB_PATH}. "
        "Refusing to run: tests must never open the real fathom.db."
    )

# Schema once per session, before the write guard (tests/conftest.py) is attached; reads then see empty tables, not "no such table".
SQLModel.metadata.create_all(_db.engine)

# The settings getters are get-or-create: the first read INSERTs the default singleton row. The real file always had those rows, so a
# read-only test never wrote; an empty file would make that first read a write and trip the write guard. Seed the defaults once here
# (what a first-boot database holds after first use), before the guard is attached. A getter missing from this list shows up as a
# "write to the REAL core.db.engine" failure naming its table: add it here.
from sqlmodel import Session  # noqa: E402

from data.moat import get_moat_score_config  # noqa: E402
from data.score_weights import get_score_weights_row  # noqa: E402
from helpers.discount_rate_config import get_discount_rate_config  # noqa: E402
from helpers.liquidity_zone_config import get_liquidity_zone_settings  # noqa: E402
from helpers.reit_dividend_yield_config import get_reit_dividend_yield_config  # noqa: E402
from helpers.weinstein_config import get_weinstein_settings  # noqa: E402

with Session(_db.engine) as _session:
    for _getter in (
        get_moat_score_config,
        get_score_weights_row,
        get_discount_rate_config,
        get_liquidity_zone_settings,
        get_reit_dividend_yield_config,
        get_weinstein_settings,
    ):
        _getter(_session)
