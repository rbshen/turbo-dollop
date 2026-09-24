import core.data_groups as dg
from pipeline import data_groups as cli


def _run(monkeypatch, *argv):
    monkeypatch.setattr(cli, "init_db", lambda: None)  # never touch the real DB
    return cli.main(list(argv))


def test_pause_all_and_resume_flip_the_master_switch(monkeypatch, capsys):
    assert _run(monkeypatch, "pause-all") == 0
    assert dg.master_on() is False
    assert "OFF" in capsys.readouterr().out
    assert _run(monkeypatch, "resume") == 0
    assert dg.master_on() is True


def test_resume_leaves_per_group_settings_untouched(monkeypatch):
    dg.set_group_enabled("news", False)
    _run(monkeypatch, "pause-all")
    _run(monkeypatch, "resume")
    assert dg.effective_state("news") == (False, "user_off")
    assert dg.group_live("fundamentals")


def test_status_lists_every_group_and_marks_unwired(monkeypatch, capsys):
    _run(monkeypatch, "status")
    out = capsys.readouterr().out
    for key in dg.GROUPS:
        assert key in out
    assert out.count("[not wired yet]") == 2
    assert "insider" in out and "user_off" in out


def _cache_rows(engine, rows):
    from datetime import datetime  # noqa: F401
    from sqlmodel import Session, SQLModel

    from core.models import FundamentalsCache

    SQLModel.metadata.create_all(engine, tables=[FundamentalsCache.__table__])
    with Session(engine) as s:
        for ticker, statement_type, fetched_at in rows:
            s.add(FundamentalsCache(ticker=ticker, statement_type=statement_type, period="latest", fetched_at=fetched_at, raw_json="{}"))
        s.commit()


def test_backfill_last_success_seeds_from_newest_cache_row_and_is_idempotent(_isolate_data_groups_engine):
    from datetime import datetime

    _cache_rows(
        _isolate_data_groups_engine,
        [
            ("AAPL", "income_statement", datetime(2026, 9, 1)),
            ("MSFT", "balance_sheet_statement", datetime(2026, 9, 10)),  # newest fundamentals
            ("AAPL", "news", datetime(2026, 8, 1)),
        ],
    )
    first = dg.backfill_last_success_from_cache()
    assert first["fundamentals"] == datetime(2026, 9, 10)
    assert first["news"] == datetime(2026, 8, 1)
    snap = dg.get_snapshot().groups
    assert snap["fundamentals"].last_success_at == datetime(2026, 9, 10)
    assert snap["segmentation"].last_success_at is None  # no cache rows -> stays empty
    assert snap["index_membership"].last_success_at is None

    second = dg.backfill_last_success_from_cache()  # re-run: nothing to change
    assert all(v is None for v in second.values())


def test_backfill_never_moves_a_newer_live_value_backwards(_isolate_data_groups_engine):
    from datetime import datetime

    _cache_rows(_isolate_data_groups_engine, [("AAPL", "news", datetime(2026, 8, 1))])
    dg.record_group_success("news")  # live success, "now"
    live = dg.get_snapshot().groups["news"].last_success_at
    dg.backfill_last_success_from_cache()
    assert dg.get_snapshot().groups["news"].last_success_at == live


def test_backfill_command_runs_through_the_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "init_db", lambda: None)
    _cache_rows(dg.engine, [])
    assert cli.main(["backfill-last-success"]) == 0
    assert "fundamentals" in capsys.readouterr().out
