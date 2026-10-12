"""The PreToolUse guard of the blind Moat-check passes (.claude/hooks/moat-pass-guard.py, docs/specs/moat-check.md "Enforcement"): what a pass
may read, write and fetch, and that everything else is blocked (exit 2), including malformed input. Throwaway folders; the audit log is
redirected with MOAT_GUARD_LOG_DIR so these tests never touch the real /tmp/moat-check/guard.log."""

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO / ".claude" / "hooks" / "moat-pass-guard.py"

_spec = importlib.util.spec_from_file_location("moat_pass_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.fixture
def world(tmp_path):
    """A moat-check base with one run folder holding pass1 and pass2, each with the three files, plus files outside the base."""
    base = tmp_path / "moat-check"
    run = base / "PM-20261012-100000"
    for n in (1, 2):
        folder = run / f"pass{n}"
        folder.mkdir(parents=True)
        for name in guard.READ_NAMES:
            (folder / name).write_text(f"pass{n} {name}")
    (base / "guard.log").write_text("log\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("the set rating")
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "CLAUDE.md").write_text("repo")
    return {"base": base, "run": run, "p1": run / "pass1", "p2": run / "pass2", "outside": outside, "tmp": tmp_path}


def decide(world, tool, tool_input, n="1"):
    allowed, reason, _ = guard.decide({"tool_name": tool, "tool_input": tool_input}, n, str(world["base"]))
    return allowed, reason


def read(world, path, n="1"):
    return decide(world, "Read", {"file_path": str(path) if isinstance(path, Path) else path}, n)


# --- Read ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["criteria.md", "block.json", "out.json"])
def test_a_pass_reads_its_own_three_files(world, name):
    assert read(world, world["p1"] / name)[0] is True
    assert read(world, world["p2"] / name, n="2")[0] is True


def test_a_pass_may_read_an_out_json_that_does_not_exist_yet(world):
    (world["p1"] / "out.json").unlink(missing_ok=True)
    assert read(world, world["p1"] / "out.json")[0] is True


def test_pass_2_cannot_read_pass_1_s_folder_and_the_reverse(world):
    for name in guard.READ_NAMES:
        ok, reason = read(world, world["p1"] / name, n="2")
        assert ok is False and reason == "another pass's folder"
        assert read(world, world["p2"] / name, n="1")[0] is False


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/home/shen",
        "/home/shen/fathom/CLAUDE.md",
        "/home/shen/fathom/backend/fathom.db",
        "/home/shen/fathom/backend/.env",
        "~/.claude/settings.json",
        "criteria.md",
        "./criteria.md",
        "../pass2/criteria.md",
        "",
        "   ",
        None,
        5,
        ["/tmp"],
        {"a": 1},
    ],
)
def test_reads_outside_the_folder_relative_empty_and_junk_paths_are_denied(world, path):
    assert read(world, path)[0] is False


def test_the_repo_the_log_the_run_folder_and_the_base_are_denied(world):
    assert read(world, world["tmp"] / "repo" / "CLAUDE.md")[0] is False
    assert read(world, world["base"] / "guard.log")[0] is False
    assert read(world, world["run"])[0] is False
    assert read(world, world["p1"])[0] is False  # the folder itself
    assert read(world, world["base"])[0] is False


def test_other_file_names_in_the_pass_folder_are_denied(world):
    (world["p1"] / "notes.txt").write_text("x")
    assert read(world, world["p1"] / "notes.txt")[0] is False
    assert read(world, world["p1"] / "criteria.md.bak")[0] is False
    assert read(world, world["p1"] / "sub" / "criteria.md")[0] is False


def test_dot_dot_traversal_is_resolved_before_judging(world):
    assert read(world, f"{world['p1']}/../pass2/criteria.md")[0] is False
    assert read(world, f"{world['p1']}/../../../../etc/passwd")[0] is False
    assert read(world, f"{world['p1']}/../pass1/criteria.md")[0] is True  # resolves to its own file


def test_a_symlink_that_leaves_the_folder_is_denied(world):
    (world["p1"] / "block.json").unlink()
    (world["p1"] / "block.json").symlink_to(world["outside"] / "secret.txt")
    assert read(world, world["p1"] / "block.json")[0] is False


def test_a_symlinked_pass_folder_that_points_at_the_other_pass_is_denied(world, tmp_path):
    link = world["run"] / "pass1_alias"
    link.symlink_to(world["p2"])
    assert read(world, link / "criteria.md", n="1")[0] is False  # resolves into pass2, and the name is not pass1 anyway
    world["p1"].rename(world["run"] / "pass1_real")
    (world["run"] / "pass1").symlink_to(world["p2"])
    assert read(world, world["run"] / "pass1" / "criteria.md", n="1")[0] is False


def test_a_symlinked_base_still_works_for_a_real_pass_folder(world, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(world["base"])
    ok, _, _ = guard.decide({"tool_name": "Read", "tool_input": {"file_path": str(alias / "PM-20261012-100000" / "pass1" / "criteria.md")}}, "1", str(world["base"]))
    assert ok is True


def test_a_nul_in_the_path_is_denied(world):
    assert read(world, str(world["p1"] / "criteria.md") + "\x00.txt")[0] is False


# --- Write -----------------------------------------------------------------------------------------------------------------------


def test_a_pass_writes_only_its_own_out_json(world):
    assert decide(world, "Write", {"file_path": str(world["p1"] / "out.json"), "content": "{}"})[0] is True
    assert decide(world, "Write", {"file_path": str(world["p2"] / "out.json")}, n="2")[0] is True


@pytest.mark.parametrize("target", ["criteria.md", "block.json", "notes.txt", "out.json.bak", "../out.json"])
def test_a_pass_cannot_write_its_inputs_or_anything_else_in_the_folder(world, target):
    assert decide(world, "Write", {"file_path": str(world["p1"] / target)})[0] is False


def test_a_pass_cannot_write_to_the_other_pass_or_outside(world):
    assert decide(world, "Write", {"file_path": str(world["p2"] / "out.json")}, n="1")[0] is False
    assert decide(world, "Write", {"file_path": str(world["outside"] / "x.txt")})[0] is False
    assert decide(world, "Write", {"file_path": "/home/shen/fathom/CLAUDE.md"})[0] is False
    assert decide(world, "Write", {"file_path": "out.json"})[0] is False
    assert decide(world, "Write", {})[0] is False


# --- WebFetch --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.reuters.com/markets/x",
        "http://example.org/a?b=1#c",
        "http://example.org:80/",
        "https://example.com:443/path",
        "https://news.example.co.uk/a-b_c",
        "https://sec.gov./x",
    ],
)
def test_ordinary_public_urls_are_allowed(world, url):
    assert decide(world, "WebFetch", {"url": url, "prompt": "p"})[0] is True


@pytest.mark.parametrize(
    "url, why",
    [
        ("file:///etc/passwd", "scheme"),
        ("FILE:///etc/passwd", "scheme"),
        ("ftp://example.com/x", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("data:text/html,x", "scheme"),
        ("http://localhost/", "dot"),
        ("http://localhost:8002/api/tickers/PM/moat", "port"),
        ("http://LOCALHOST./", "dot"),
        ("http://127.0.0.1/", "IP"),
        ("http://127.0.0.1:8002/api/tickers/PM/moat", "port"),
        ("http://127.1/", "IP"),
        ("http://0x7f000001/", "dot"),
        ("http://0x7f.0.0.1/", "IP"),
        ("http://2130706433/", "dot"),
        ("http://0177.0.0.1/", "IP"),
        ("http://[::1]/", "dot"),
        ("http://[::ffff:127.0.0.1]/", "IPv6"),
        ("http://10.0.0.5/", "IP"),
        ("http://172.16.0.9/", "IP"),
        ("http://192.168.1.20/", "IP"),
        ("http://169.254.169.254/latest/meta-data", "IP"),
        ("http://8.8.8.8/", "IP"),
        ("https://93.184.216.34/", "IP"),
        ("http://0.0.0.0:8002/", "port"),
        ("http://example.com:8002/", "port"),
        ("https://example.com:8443/", "port"),
        ("http://example.com:81/", "port"),
        ("http://user:pw@example.com/", "credentials"),
        ("http://user@example.com/", "credentials"),
        ("http://example.com@127.0.0.1/", "credentials"),
        ("http://printer.local/", "local"),
        ("http://box.lan/", "local"),
        ("http://app.internal/", "local"),
        ("http://a.localhost/", "local"),
        ("http://foo/", "dot"),
        ("//example.com/x", "scheme"),
        ("example.com", "scheme"),
        ("not a url", "whitespace"),
        ("http://example.com/x y", "whitespace"),
        ("http://example.com/\nx", "whitespace"),
        ("", "empty"),
        ("   ", "empty"),
        (None, "empty"),
        (7, "empty"),
        ("http://", "no host"),
        ("http://exa_mple.com/", "unusual"),
    ],
)
def test_local_network_and_odd_urls_are_denied(world, url, why):
    allowed, reason = decide(world, "WebFetch", {"url": url, "prompt": "p"})
    assert allowed is False and why.lower() in reason.lower(), (url, reason)


def test_a_missing_url_is_denied(world):
    assert decide(world, "WebFetch", {"prompt": "p"})[0] is False


def test_residual_risk_a_name_that_resolves_to_this_machine_is_not_caught(world):
    """Accepted and recorded in docs/decisions.md: the guard judges the spelling of the host, not what DNS returns."""
    assert decide(world, "WebFetch", {"url": "http://127.0.0.1.nip.io/"})[0] is True


# --- other tools -----------------------------------------------------------------------------------------------------------------


def test_web_search_and_tool_search_are_allowed(world):
    assert decide(world, "WebSearch", {"query": "nicotine pouch share 2026"})[0] is True
    assert decide(world, "ToolSearch", {"query": "select:WebSearch", "max_results": 1})[0] is True


@pytest.mark.parametrize("tool", ["Bash", "Grep", "Glob", "Edit", "MultiEdit", "NotebookEdit", "Agent", "Task", "TodoWrite", "mcp__x__y", "read", "READ", ""])
def test_every_other_tool_is_denied(world, tool):
    assert decide(world, tool, {"command": "cat /etc/passwd", "pattern": "x", "file_path": str(world["p1"] / "criteria.md")})[0] is False


@pytest.mark.parametrize("payload", [None, [], "Read", 5, {}, {"tool_name": "Read"}, {"tool_input": {}}, {"tool_name": 5, "tool_input": {}}, {"tool_name": "Read", "tool_input": "x"}])
def test_malformed_payloads_are_denied(world, payload):
    assert guard.decide(payload, "1", str(world["base"]))[0] is False


@pytest.mark.parametrize("number", ["", "0", "3", "pass1", None, "1 "])
def test_a_bad_pass_number_denies_everything(world, number):
    assert guard.decide({"tool_name": "WebSearch", "tool_input": {"query": "x"}}, number, str(world["base"]))[0] is False


# --- main(): exit codes and the audit log -----------------------------------------------------------------------------------------


def run_main(world, payload, n="1", raw=None):
    stdin = io.StringIO(raw if raw is not None else json.dumps(payload))
    stderr = io.StringIO()
    code = guard.main([n], stdin=stdin, stderr=stderr, base=str(world["base"]))
    return code, stderr.getvalue()


@pytest.fixture(autouse=True)
def _log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MOAT_GUARD_LOG_DIR", str(tmp_path / "logs"))


def test_exit_0_for_an_allowed_call_and_2_for_a_denied_one(world):
    assert run_main(world, {"tool_name": "WebSearch", "tool_input": {"query": "q"}})[0] == 0
    code, err = run_main(world, {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}})
    assert code == 2 and err.startswith("Blocked by the Moat check guard") and "not a file in a pass folder" in err


@pytest.mark.parametrize("raw", ["", "not json", "{", "null", "[]", '"x"', "{}", "\x00"])
def test_malformed_stdin_exits_2_never_0_and_never_crashes(world, raw):
    assert run_main(world, None, raw=raw)[0] == 2


def test_a_missing_pass_argument_exits_2(world):
    code = guard.main([], stdin=io.StringIO(json.dumps({"tool_name": "WebSearch", "tool_input": {}})), stderr=io.StringIO(), base=str(world["base"]))
    assert code == 2


def test_every_decision_is_logged_with_pass_tool_and_detail(world, tmp_path):
    run_main(world, {"tool_name": "WebSearch", "tool_input": {"query": "pouch share"}, "agent_id": "a1"})
    run_main(world, {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}, n="2")
    lines = (tmp_path / "logs" / "guard.log").read_text().splitlines()
    assert len(lines) == 2
    assert " pass1 ALLOW WebSearch pouch share" in lines[0] and lines[0].endswith("agent=a1")
    assert " pass2 DENY  Read /etc/passwd (" in lines[1]


def test_a_malformed_call_is_logged_too(world, tmp_path):
    run_main(world, None, raw="garbage")
    assert "DENY" in (tmp_path / "logs" / "guard.log").read_text()


def test_the_log_is_capped(world, tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "guard.log").write_text(("y" * 99 + "\n") * 12_000)  # about 1.2 MB
    run_main(world, {"tool_name": "WebSearch", "tool_input": {"query": "q"}})
    size = (log_dir / "guard.log").stat().st_size
    assert size < guard.LOG_CAP_BYTES and size > 100_000
    assert (log_dir / "guard.log").read_text().splitlines()[-1].endswith("agent=")


def test_a_logging_failure_never_changes_the_decision(world, tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the log folder should be")
    monkeypatch.setenv("MOAT_GUARD_LOG_DIR", str(blocker / "sub"))
    assert run_main(world, {"tool_name": "WebSearch", "tool_input": {"query": "q"}})[0] == 0
    assert run_main(world, {"tool_name": "Bash", "tool_input": {"command": "ls"}})[0] == 2


# --- the script as the hook runs it ----------------------------------------------------------------------------------------------


def run_script(payload_text, n, tmp_path, extra_env=None):
    env = {**os.environ, "MOAT_GUARD_LOG_DIR": str(tmp_path / "scriptlogs"), **(extra_env or {})}
    return subprocess.run([sys.executable, str(GUARD_PATH), n], input=payload_text, text=True, capture_output=True, env=env, timeout=30)


def test_the_script_blocks_with_exit_2_and_allows_with_exit_0(tmp_path):
    assert run_script(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}), "1", tmp_path).returncode == 2
    assert run_script(json.dumps({"tool_name": "WebSearch", "tool_input": {"query": "x"}}), "2", tmp_path).returncode == 0
    assert run_script("garbage", "1", tmp_path).returncode == 2
    assert run_script("", "1", tmp_path).returncode == 2


def test_the_script_has_no_syntax_problem_and_no_third_exit_code(tmp_path):
    compile(GUARD_PATH.read_text(), str(GUARD_PATH), "exec")
    codes = {run_script(t, n, tmp_path).returncode for t in ("", "{}", "[]", "null", '{"tool_name":"Bash","tool_input":{}}') for n in ("1", "2", "", "x")}
    assert codes == {2}


def test_the_environment_variable_moves_only_the_log_not_the_allowed_folder(tmp_path):
    inside_other_base = tmp_path / "logs" / "RUN" / "pass1" / "criteria.md"
    inside_other_base.parent.mkdir(parents=True)
    inside_other_base.write_text("x")
    result = run_script(json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(inside_other_base)}}), "1", tmp_path, {"MOAT_GUARD_LOG_DIR": str(tmp_path / "logs")})
    assert result.returncode == 2  # a folder shaped like a run folder under the LOG dir is still not under /tmp/moat-check
