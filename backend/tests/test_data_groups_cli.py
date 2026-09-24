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
    assert out.count("[not wired yet]") == 4
    assert "insider" in out and "user_off" in out
