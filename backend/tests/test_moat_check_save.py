"""pipeline/moat_check_save.py (docs/specs/moat-check.md, step 4): validates two pass files, reconciles, appends one row; every refusal
writes nothing; warnings print after the result; no rating or score is touched; not a cron job. Throwaway in-memory engines."""

import json
from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.cron_health as cron_health
import pipeline.moat_check_save as save_mod
from core.models import FundamentalsCache, MoatCheck, TickerMoat, TickerScore
from tests.test_moat_check import make_record

T0 = datetime(2026, 10, 12, 10, 0)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def write(tmp_path, name, record):
    path = tmp_path / name
    path.write_text(record if isinstance(record, str) else json.dumps(record))
    return str(path)


def run(engine, tmp_path, p1, p2, *extra, ticker="PM"):
    return save_mod.main([ticker, write(tmp_path, "p1.json", p1), write(tmp_path, "p2.json", p2), *extra], engine=engine)


def rows(engine):
    with Session(engine) as session:
        return session.exec(select(MoatCheck).order_by(MoatCheck.id)).all()


def test_two_agreeing_passes_save_one_stable_row_and_print_the_result(engine, tmp_path, capsys):
    assert run(engine, tmp_path, make_record(rating="wide_moat"), make_record(rating="wide_moat")) == 0
    [row] = rows(engine)
    assert (row.ticker, row.status, row.rating) == ("PM", "stable", "wide_moat")
    assert capsys.readouterr().out == "PM: wide_moat (stable), confidence Medium, proof independent, row 1\n"


def test_split_passes_save_an_inconclusive_row(engine, tmp_path, capsys):
    assert run(engine, tmp_path, make_record(rating="wide_moat"), make_record(rating="narrow_moat")) == 0
    [row] = rows(engine)
    assert row.status == "inconclusive" and row.rating is None
    assert capsys.readouterr().out.startswith("PM: inconclusive (inconclusive), confidence Low")


def test_a_rerun_appends_a_second_row(engine, tmp_path):
    for _ in range(2):
        assert run(engine, tmp_path, make_record(), make_record()) == 0
    assert [r.id for r in rows(engine)] == [1, 2]


def test_the_ticker_argument_is_normalised(engine, tmp_path):
    assert run(engine, tmp_path, make_record(ticker="BRK-B"), make_record(ticker="BRK-B"), ticker="brk.b") == 0
    assert rows(engine)[0].ticker == "BRK-B"


def test_empty_prose_is_saved_and_printed_as_warnings(engine, tmp_path, capsys):
    empty = make_record()
    empty["narrative"], empty["would_raise"] = "", "  "
    assert run(engine, tmp_path, empty, make_record()) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("PM: narrow_moat (stable)")
    assert out[1:] == ["warning: pass 1: narrative is empty (saved as given)", "warning: pass 1: would_raise is empty (saved as given)"]
    assert len(rows(engine)) == 1


def test_a_run_date_mismatch_is_a_warning_and_the_row_is_still_saved(engine, tmp_path, capsys):
    assert run(engine, tmp_path, make_record(), make_record(), "2026-10-13") == 0
    out = capsys.readouterr().out
    assert "warning: pass 1: checked_date 2026-10-12 differs from run date 2026-10-13" in out
    assert "warning: pass 2: checked_date 2026-10-12 differs from run date 2026-10-13" in out
    assert len(rows(engine)) == 1


def test_a_matching_run_date_gives_no_warning(engine, tmp_path, capsys):
    assert run(engine, tmp_path, make_record(), make_record(), "2026-10-12") == 0
    assert "warning" not in capsys.readouterr().out


def test_a_bad_run_date_is_refused_and_nothing_is_saved(engine, tmp_path, capsys):
    assert run(engine, tmp_path, make_record(), make_record(), "12/10/2026") == 2
    assert "run_date" in capsys.readouterr().err and rows(engine) == []


def test_an_invalid_pass_is_refused_with_every_problem_and_nothing_is_saved(engine, tmp_path, capsys):
    bad = make_record()
    bad["reading"], bad["checked_date"] = "great", "nope"
    assert run(engine, tmp_path, make_record(), bad) == 2
    err = capsys.readouterr().err
    assert "nothing was saved" in err and "reading" in err and "checked_date" in err
    assert rows(engine) == []


def test_a_pass_with_a_retired_key_is_refused(engine, tmp_path, capsys):
    bad = make_record()
    bad["tag"] = None
    assert run(engine, tmp_path, make_record(), bad) == 2
    assert "unexpected key(s) tag" in capsys.readouterr().err and rows(engine) == []


@pytest.mark.parametrize("content", ["{not json", "", "[]"])
def test_an_unreadable_or_non_record_pass_file_is_refused(engine, tmp_path, capsys, content):
    assert run(engine, tmp_path, make_record(), content) == 2
    assert rows(engine) == []


def test_a_missing_pass_file_is_refused(engine, tmp_path, capsys):
    assert save_mod.main(["PM", str(tmp_path / "nope.json"), write(tmp_path, "p2.json", make_record())], engine=engine) == 2
    assert "cannot read a pass file" in capsys.readouterr().err and rows(engine) == []


def test_a_known_etf_is_refused_with_its_own_exit_code(engine, tmp_path, capsys):
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="SPY", statement_type="profile", period="latest", fetched_at=T0, raw_json='[{"isEtf": true}]'))
        session.commit()
    assert run(engine, tmp_path, make_record(ticker="SPY"), make_record(ticker="SPY"), ticker="SPY") == 3
    assert "ETF" in capsys.readouterr().err and rows(engine) == []


def test_a_missing_table_stops_the_script_and_it_creates_nothing(tmp_path, capsys):
    bare = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert run(bare, tmp_path, make_record(), make_record()) == 1
    assert "never creates tables" in capsys.readouterr().err
    from sqlalchemy import inspect

    assert inspect(bare).get_table_names() == []


def test_a_save_touches_no_rating_and_no_score(engine, tmp_path):
    with Session(engine) as session:
        session.add(TickerMoat(ticker="PM", moat="wide_moat", updated_at=T0))
        session.commit()
    assert run(engine, tmp_path, make_record(rating="no_moat"), make_record(rating="no_moat")) == 0
    with Session(engine) as session:
        assert session.get(TickerMoat, "PM").moat == "wide_moat"
        assert session.exec(select(TickerScore)).all() == []


def test_the_script_is_not_a_cron_job_and_never_calls_init_db_or_the_network():
    import ast

    tree = ast.parse(open(save_mod.__file__).read())
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert not used & {"cron_heartbeat", "init_db", "fmp_client", "compute_ticker_score", "set_ticker_moat", "create_all"}
    assert not any("moat_check" in name for name in cron_health.CRON_JOB_NAMES)
