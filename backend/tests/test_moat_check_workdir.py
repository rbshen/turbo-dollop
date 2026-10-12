"""pipeline/moat_check_prepare.py and moat_check_finish.py (docs/specs/moat-check.md, "The command flow" and "Enforcement"): the run
folders, the byte-identical criteria copies, RUN_DATE and the 18-month cutoff, the sweep, ticker validation, the guard probe, and the
finish refusals. Throwaway folders only; nothing here touches the real /tmp/moat-check."""

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

import pipeline.moat_check_finish as finish_mod
import pipeline.moat_check_prepare as prep
from core.models import FundamentalsCache, TickerMoat
from tests.test_moat_check_block import FETCHED, income_row, profile_row, shared_bars

NOW = datetime(2026, 10, 12, 10, 30, 0)
TODAY = date(2026, 10, 12)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "block.db"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([profile_row(), income_row(), *shared_bars()])
        session.add(TickerMoat(ticker="PM", moat="wide_moat", updated_at=FETCHED))  # a set rating that must never reach the folders
        session.commit()
    engine.dispose()
    return path


def run_prepare(db, tmp_path, ticker="PM", **kw):
    return prep.prepare(ticker, base=tmp_path / "mc", today=TODAY, now=NOW, db_path=db, probe=False, **kw)


# --- the 18-month cutoff ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "run_date, expected",
    [
        (date(2026, 10, 12), date(2025, 4, 12)),
        (date(2026, 10, 11), date(2025, 4, 11)),  # the date the v5.1 round hard-coded
        (date(2026, 1, 15), date(2024, 7, 15)),
        (date(2026, 3, 31), date(2024, 9, 30)),  # day clamped: September has 30 days
        (date(2026, 8, 31), date(2025, 2, 28)),  # 2025 is not a leap year
        (date(2025, 8, 31), date(2024, 2, 29)),  # 2024 is
        (date(2025, 8, 30), date(2024, 2, 29)),
        (date(2024, 2, 29), date(2022, 8, 29)),
        (date(2026, 6, 30), date(2024, 12, 30)),
        (date(2026, 12, 31), date(2025, 6, 30)),
        (date(2027, 1, 1), date(2025, 7, 1)),
        (date(2026, 7, 15), date(2025, 1, 15)),
    ],
)
def test_the_stale_cutoff_is_eighteen_calendar_months_back_with_the_day_clamped(run_date, expected):
    assert prep.stale_cutoff(run_date) == expected


def test_the_stale_cutoff_takes_other_month_counts():
    assert prep.stale_cutoff(date(2026, 10, 12), months=12) == date(2025, 10, 12)
    assert prep.stale_cutoff(date(2026, 3, 31), months=1) == date(2026, 2, 28)
    assert prep.stale_cutoff(date(2026, 1, 31), months=0) == date(2026, 1, 31)


# --- ticker validation -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [("PM", "PM"), ("pm", "PM"), (" aapl ", "AAPL"), ("BRK.B", "BRK-B"), ("brk-b", "BRK-B"), ("BF.B", "BF-B"), ("T", "T"), ("GOOGL", "GOOGL")])
def test_a_single_ticker_symbol_is_accepted_and_normalised(raw, expected):
    assert prep.valid_ticker(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "AAPL; rm -rf /", "AAPL MSFT", "AAPL,MSFT", "../x", "a/b", "$(id)", "`id`", "AAPL&&ls", "AAPL\nMSFT", "1AAPL", "-AAPL", ".A", "TOOLONGSYMBOL", "A.B.C.D", "AAPL|x", "AAPL'", 'AAPL"', "AAPL>x", None, "é"],
)
def test_anything_but_a_single_ticker_symbol_is_refused(raw):
    with pytest.raises((prep.PrepareRefused, AttributeError)):
        prep.valid_ticker(raw)


def test_a_bad_ticker_creates_nothing(db, tmp_path):
    with pytest.raises(prep.PrepareRefused):
        run_prepare(db, tmp_path, ticker="AAPL; ls")
    assert not (tmp_path / "mc").exists() or list((tmp_path / "mc").iterdir()) == []


# --- the run folder --------------------------------------------------------------------------------------------------------------


def test_prepare_creates_two_pass_folders_each_with_the_criteria_and_the_block(db, tmp_path):
    result = run_prepare(db, tmp_path)
    run = result["run_dir"]
    assert run == tmp_path / "mc" / "PM-20261012-103000" and result["ticker"] == "PM"
    assert result["run_date"] == TODAY and result["stale_cutoff"] == date(2025, 4, 12)
    for n in (1, 2):
        folder = run / f"pass{n}"
        assert sorted(p.name for p in folder.iterdir()) == ["block.json", "criteria.md"]
        assert (folder / "criteria.md").read_bytes() == prep.CRITERIA_SOURCE.read_bytes()  # byte-identical copy
    assert (run / "pass1" / "block.json").read_bytes() == (run / "pass2" / "block.json").read_bytes()
    block = json.loads((run / "pass1" / "block.json").read_text())
    assert block["ticker"] == "PM" and block["industry"] == "Tobacco"


def test_nothing_about_a_stored_rating_reaches_the_folders(db, tmp_path):
    run = run_prepare(db, tmp_path)["run_dir"]
    for path in run.rglob("block.json"):
        text = path.read_text().lower()
        for leak in ("wide_moat", "narrow_moat", "no_moat", "set rating", "tickermoat", "overall", "verdict"):
            assert leak not in text, leak


def test_the_criteria_copy_is_the_committed_final_file(tmp_path):
    assert prep.CRITERIA_SOURCE.name == "moat-criteria.md" and prep.CRITERIA_SOURCE.read_text().startswith("# moat-criteria-v5.2")


def test_the_folders_are_private_to_the_user(db, tmp_path):
    run = run_prepare(db, tmp_path)["run_dir"]
    assert (os.stat(run / "pass1").st_mode & 0o077) == 0 and (os.stat(tmp_path / "mc").st_mode & 0o077) == 0


def test_two_runs_in_the_same_second_get_different_folders(db, tmp_path):
    first, second = run_prepare(db, tmp_path)["run_dir"], run_prepare(db, tmp_path)["run_dir"]
    assert first != second and first.exists() and second.exists()


def test_a_ticker_with_no_cached_data_is_refused_before_anything_is_created(db, tmp_path):
    with pytest.raises(prep.PrepareRefused, match="no cached profile"):
        run_prepare(db, tmp_path, ticker="ZZZZ")
    assert [p for p in (tmp_path / "mc").iterdir()] == []


def test_a_known_etf_is_refused_before_anything_is_created(db, tmp_path):
    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as session:
        session.add(profile_row("SPY", isEtf=True))
        session.add(income_row("SPY"))
        session.add_all(shared_bars("SPY"))
        session.commit()
    engine.dispose()
    with pytest.raises(prep.PrepareRefused, match="ETF or fund"):
        run_prepare(db, tmp_path, ticker="SPY")
    assert [p for p in (tmp_path / "mc").iterdir()] == []


def test_the_database_file_is_not_changed(db, tmp_path):
    import hashlib

    before = hashlib.sha256(db.read_bytes()).hexdigest()
    run_prepare(db, tmp_path)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


# --- the sweep -------------------------------------------------------------------------------------------------------------------


def make_old(path: Path, age: timedelta):
    stamp = (NOW - age).timestamp()
    os.utime(path, (stamp, stamp))


def test_the_sweep_removes_run_folders_over_a_day_old_and_keeps_the_rest(tmp_path):
    base = tmp_path / "mc"
    old, fresh, edge = base / "OLD-1", base / "FRESH-1", base / "EDGE-1"
    for folder in (old, fresh, edge):
        (folder / "pass1").mkdir(parents=True)
        (folder / "pass1" / "out.json").write_text("{}")
    (base / "guard.log").write_text("log")
    make_old(old, timedelta(days=2))
    make_old(fresh, timedelta(hours=3))
    make_old(edge, timedelta(hours=23, minutes=59))
    removed = prep.sweep(base, NOW)
    assert removed == [old] and not old.exists() and fresh.exists() and edge.exists()
    assert (base / "guard.log").exists()


def test_the_sweep_never_touches_files_symlinks_or_what_they_point_at(tmp_path):
    base = tmp_path / "mc"
    base.mkdir()
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    link = base / "LINK-1"
    link.symlink_to(target)
    stray = base / "stray.txt"
    stray.write_text("x")
    make_old(target, timedelta(days=9))
    make_old(stray, timedelta(days=9))
    assert prep.sweep(base, NOW) == [] and (target / "keep.txt").exists() and link.is_symlink() and stray.exists()


def test_the_sweep_of_a_missing_base_is_a_no_op(tmp_path):
    assert prep.sweep(tmp_path / "nope", NOW) == []


def test_prepare_sweeps_old_runs_first(db, tmp_path):
    base = tmp_path / "mc"
    old = base / "PM-OLD"
    old.mkdir(parents=True)
    make_old(old, timedelta(days=3))
    run_prepare(db, tmp_path)
    assert not old.exists()


# --- the guard probe -------------------------------------------------------------------------------------------------------------


def fake_guard(tmp_path):
    """A stand-in hook: exit 0 only for a Read inside pass<n> of a run folder under tmp_path/mc, else 2."""
    script = tmp_path / "fake_guard.py"
    script.write_text(
        "import json, sys\n"
        "n = sys.argv[1]\n"
        "p = json.load(sys.stdin)['tool_input']['file_path']\n"
        f"ok = p.startswith({str(tmp_path / 'mc')!r}) and ('/pass' + n + '/') in p\n"
        "sys.exit(0 if ok else 2)\n"
    )
    return [(n, f"{sys.executable} {script} {n}") for n in (1, 2)]


def test_the_probe_passes_when_the_hook_denies_and_allows_correctly(db, tmp_path):
    result = prep.prepare("PM", base=tmp_path / "mc", today=TODAY, now=NOW, db_path=db, probe=True, commands=fake_guard(tmp_path))
    assert result["run_dir"].exists()


def test_a_hook_that_allows_everything_fails_the_probe_and_the_run_folder_is_removed(db, tmp_path):
    script = tmp_path / "open_guard.py"
    script.write_text("import sys\nsys.exit(0)\n")
    with pytest.raises(prep.PrepareRefused, match="guard hook of pass 1 answered exit 0 \\(expected 2\\)"):
        prep.prepare("PM", base=tmp_path / "mc", today=TODAY, now=NOW, db_path=db, probe=True, commands=[(1, f"{sys.executable} {script}")])
    assert list((tmp_path / "mc").iterdir()) == []


def test_a_hook_command_that_does_not_run_fails_the_probe(db, tmp_path):
    with pytest.raises(prep.PrepareRefused, match="expected 2"):
        prep.prepare("PM", base=tmp_path / "mc", today=TODAY, now=NOW, db_path=db, probe=True, commands=[(1, "no-such-program-xyz")])  # exit 127
    assert list((tmp_path / "mc").iterdir()) == []


def test_a_hook_that_denies_its_own_folder_fails_the_probe(db, tmp_path):
    script = tmp_path / "closed_guard.py"
    script.write_text("import sys\nsys.exit(2)\n")
    with pytest.raises(prep.PrepareRefused, match="expected 0"):
        prep.prepare("PM", base=tmp_path / "mc", today=TODAY, now=NOW, db_path=db, probe=True, commands=[(1, f"{sys.executable} {script}")])


def test_the_hook_commands_in_the_real_agent_files_are_read_and_run_the_real_guard(tmp_path):
    commands = prep.guard_commands()
    assert [n for n, _ in commands] == [1, 2]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(prep.REPO_ROOT), "MOAT_GUARD_LOG_DIR": str(tmp_path / "logs")}
    for number, command in commands:
        assert command == f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/moat-pass-guard.py" {number}'
        denied = subprocess.run(["sh", "-c", command], input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}), text=True, capture_output=True, env=env)
        allowed = subprocess.run(["sh", "-c", command], input=json.dumps({"tool_name": "WebSearch", "tool_input": {"query": "q"}}), text=True, capture_output=True, env=env)
        assert denied.returncode == 2 and allowed.returncode == 0


def test_an_agent_file_without_a_hook_command_is_refused(tmp_path):
    bare = tmp_path / "agent.md"
    bare.write_text("---\nname: x\n---\nbody\n")
    with pytest.raises(prep.PrepareRefused, match="no hook command"):
        prep.guard_commands((bare,))


# --- main() ----------------------------------------------------------------------------------------------------------------------


def test_main_prints_the_values_and_the_screen_only_cache_dates(db, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(prep, "BASE_DIR", tmp_path / "mc")
    real_prepare = prep.prepare
    monkeypatch.setattr(prep, "prepare", lambda t: real_prepare(t, base=tmp_path / "mc", today=TODAY, now=NOW, db_path=db, probe=False))
    assert prep.main(["pm"]) == 0
    out = capsys.readouterr().out.splitlines()
    values = dict(line.split("=", 1) for line in out if "=" in line and not line.startswith(" "))
    assert values["run_date"] == "2026-10-12" and values["stale_cutoff"] == "2025-04-12" and values["ticker"] == "PM"
    assert values["pass1_dir"] == values["run_dir"] + "/pass1" and values["pass2_dir"] == values["run_dir"] + "/pass2"
    assert any(line.startswith("margins: gross and net margin (industry: Tobacco)") for line in out)
    assert any("statement fiscal dates read: 2022-12-31 to 2025-12-31 (4 years)" in line for line in out)
    assert any(line.startswith("last bar date: ") for line in out)


def test_main_refuses_with_exit_2_and_prints_why(db, tmp_path, monkeypatch, capsys):
    real_prepare = prep.prepare
    monkeypatch.setattr(prep, "prepare", lambda t: real_prepare(t, base=tmp_path / "mc", today=TODAY, now=NOW, db_path=db, probe=False))
    assert prep.main(["ZZZZ"]) == 2
    assert "no cached profile" in capsys.readouterr().err
    assert prep.main(["AAPL; ls"]) == 2
    assert prep.main([]) == 2 and prep.main(["A", "B"]) == 2


def test_main_exits_3_when_the_guard_probe_fails(monkeypatch, capsys):
    def boom(ticker):
        raise prep.PrepareRefused("the guard hook of pass 1 answered exit 0 (expected 2) for /etc/passwd: ")

    monkeypatch.setattr(prep, "prepare", boom)
    assert prep.main(["PM"]) == 3


def test_prepare_reads_no_rating_score_or_check_table():
    import ast

    tree = ast.parse(Path(prep.__file__).read_text())
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert not used & {"TickerMoat", "TickerScore", "MoatCheck", "get_ticker_moat", "get_latest_moat_check", "init_db", "fmp_client"}


# --- finish ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def base(tmp_path):
    base = tmp_path / "mc"
    (base / "PM-1" / "pass1").mkdir(parents=True)
    (base / "PM-1" / "pass1" / "out.json").write_text("{}")
    (base / "guard.log").write_text("log")
    return base


def test_finish_removes_a_run_folder_and_everything_in_it(base):
    assert finish_mod.finish(base / "PM-1", base=base) is True
    assert not (base / "PM-1").exists() and (base / "guard.log").exists() and base.exists()


def test_finish_on_a_folder_already_gone_is_not_an_error(base):
    assert finish_mod.finish(base / "PM-9", base=base) is False


@pytest.mark.parametrize("make", [
    lambda b, t: b,  # the base itself
    lambda b, t: b / "guard.log",  # a file
    lambda b, t: b / "PM-1" / "pass1",  # nested, not a run folder
    lambda b, t: b / "PM-1" / "pass1" / "out.json",
    lambda b, t: t / "outside",  # outside the base
    lambda b, t: t,  # the base's parent
    lambda b, t: Path("/"),
    lambda b, t: Path("/tmp"),
    lambda b, t: Path("/home/shen"),
    lambda b, t: Path("relative/run"),
    lambda b, t: Path(""),
    lambda b, t: b / ".." / "outside",  # traversal out
    lambda b, t: b / "PM-1" / ".." / "..",  # traversal to the parent
])
def test_finish_refuses_anything_that_is_not_a_run_folder_directly_under_the_base(base, tmp_path, make):
    (tmp_path / "outside").mkdir(exist_ok=True)
    (tmp_path / "outside" / "keep.txt").write_text("x")
    with pytest.raises(finish_mod.FinishRefused):
        finish_mod.finish(make(base, tmp_path), base=base)
    assert (base / "PM-1" / "pass1" / "out.json").exists() and (base / "guard.log").exists() and (tmp_path / "outside" / "keep.txt").exists()


def test_finish_refuses_a_symlink_and_leaves_its_target_alone(base, tmp_path):
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    (base / "LINK-1").symlink_to(target)
    with pytest.raises(finish_mod.FinishRefused, match="symlink"):
        finish_mod.finish(base / "LINK-1", base=base)
    assert (target / "keep.txt").exists()


def test_finish_refuses_a_path_that_reaches_outside_through_a_linked_parent(base, tmp_path):
    other = tmp_path / "other"
    (other / "RUN-1").mkdir(parents=True)
    link = tmp_path / "alias"
    link.symlink_to(other)
    with pytest.raises(finish_mod.FinishRefused):
        finish_mod.finish(link / "RUN-1", base=base)
    assert (other / "RUN-1").exists()


@pytest.mark.parametrize("bad", ["", "   ", "x\x00y"])
def test_finish_refuses_empty_and_invalid_paths(base, bad):
    with pytest.raises(finish_mod.FinishRefused):
        finish_mod.finish(bad, base=base)


def test_finish_main_exit_codes(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    assert finish_mod.main([str(outside)]) == 2 and outside.exists()
    assert "refused" in capsys.readouterr().err
    assert finish_mod.main([]) == 2 and finish_mod.main(["a", "b"]) == 2
    assert finish_mod.main(["/tmp/moat-check"]) == 2  # the real base itself is never removable
    assert finish_mod.main(["/"]) == 2
