"""The test process never opens the real backend/fathom.db (backend/conftest.py points DATABASE_PATH at a throwaway file before
any app import, so every `from core.db import engine` module binds that file). Two layers: the runtime state, and a static scan
that fails when production code opens a database some other way (a new module the redirect would not reach)."""

import ast
import os
from pathlib import Path

from sqlalchemy import text

import core.db as core_db
from conftest import real_engine
from core.config import BASE_DIR

REAL_DB = (BASE_DIR / "fathom.db").resolve()
PROD_DIRS = ("core", "clients", "data", "helpers", "scoring", "analysis", "scrapers", "pipeline", "scripts")

# Files allowed to open a database themselves. Each takes its path from core.db.DB_PATH / settings (the redirected value in tests)
# or from an argument; a NEW entry here is a deliberate decision, not a drive-by.
ENGINE_OPENERS = {
    "core/db.py",  # the one writing engine
    "pipeline/backup_db.py",  # sqlite3 backup API on DEFAULT_DB_PATH (from settings)
    "pipeline/moat_check_block.py",  # mode=ro on DB_PATH
    "pipeline/wipe_untouched_tickers.py",  # mode=ro on DB_PATH
    "pipeline/cache_history_audit.py",  # mode=ro on a path argument, default DB_PATH
}
DATABASE_PATH_READERS = {"core/db.py", "pipeline/backup_db.py"}
FATHOM_DB_LITERAL_ALLOWED = {"core/config.py"}  # the default value of Settings.database_path


def _production_files():
    for d in PROD_DIRS:
        for path in sorted((BASE_DIR / d).rglob("*.py")):
            rel = path.relative_to(BASE_DIR).as_posix()
            if path.name.startswith("test_") or "/tests/" in f"/{rel}" or ".venv" in rel:
                continue
            yield rel, ast.parse(path.read_text(), filename=rel)


def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def test_the_test_engine_is_the_throwaway_file_not_the_real_database():
    assert core_db.DB_PATH != REAL_DB
    assert core_db.DB_PATH.name == "fathom-test.db"
    assert Path(os.environ["DATABASE_PATH"]).resolve() == core_db.DB_PATH
    assert Path(real_engine.url.database).resolve() == core_db.DB_PATH
    with real_engine.connect() as conn:  # a read; the write guard allows it
        files = {Path(row[2]).resolve() for row in conn.execute(text("PRAGMA database_list")) if row[2]}
    assert files == {core_db.DB_PATH}


def test_the_throwaway_database_has_the_schema_and_no_rows():
    with real_engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {"tickerscore", "fundamentalscache", "watchlist"} <= tables
        assert conn.execute(text("SELECT count(*) FROM tickerscore")).scalar() == 0


def test_only_the_known_modules_open_a_database():
    openers = set()
    for rel, tree in _production_files():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name == "create_engine" or (name == "connect" and isinstance(fn, ast.Attribute) and getattr(fn.value, "id", "") == "sqlite3"):
                    openers.add(rel)
    assert openers <= ENGINE_OPENERS, f"opens its own database; route it through core.db.engine/DB_PATH or add it to ENGINE_OPENERS on purpose: {sorted(openers - ENGINE_OPENERS)}"


def test_only_the_known_modules_read_the_database_path_setting():
    readers = {rel for rel, tree in _production_files() for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "database_path"}
    assert readers <= DATABASE_PATH_READERS, f"reads settings.database_path directly (use core.db.DB_PATH): {sorted(readers - DATABASE_PATH_READERS)}"


def test_no_production_module_names_the_real_file():
    named = set()
    for rel, tree in _production_files():
        docs = _docstring_nodes(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and "fathom.db" in n.value and id(n) not in docs:
                named.add(rel)
    assert named <= FATHOM_DB_LITERAL_ALLOWED, f"hard-codes fathom.db (a path the test redirect cannot reach): {sorted(named - FATHOM_DB_LITERAL_ALLOWED)}"
