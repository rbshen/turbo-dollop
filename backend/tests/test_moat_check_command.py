"""The /moat-check command and its two pass agents (.claude/commands/moat-check.md, .claude/agents/moat-pass-{1,2}.md): thin, no criteria
embedded, no reference to a stored rating, the exact tool allowlist and the guard hook wired with the right pass number. Static checks on the
committed files; whether Claude Code really runs the hook is what the phase 6 trial proves."""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMMAND = REPO / ".claude" / "commands" / "moat-check.md"
AGENTS = {1: REPO / ".claude" / "agents" / "moat-pass-1.md", 2: REPO / ".claude" / "agents" / "moat-pass-2.md"}
CRITERIA = REPO / "docs" / "specs" / "moat-criteria.md"
GUARD = REPO / ".claude" / "hooks" / "moat-pass-guard.py"

# Nothing in the command or the agents may name where a set rating or an earlier check lives, or a rating value.
FORBIDDEN = ["TickerMoat", "TickerScore", "MoatCheck", "fathom.db", "wide_moat", "narrow_moat", "no_moat", "/api/", "/tickers/", "set rating"]


def split(path: Path):
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, f"{path.name} has no frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2), text


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def shingles(text: str, size: int = 6) -> set[tuple]:
    w = words(text)
    return {tuple(w[i : i + size]) for i in range(len(w) - size + 1)}


# --- the command -----------------------------------------------------------------------------------------------------------------


def test_the_command_exists_at_the_specs_path_and_has_its_frontmatter():
    front, body, _ = split(COMMAND)
    assert front["disable-model-invocation"] is True
    assert front["argument-hint"] == "<ticker>"
    assert front["description"].startswith("Run the independent Moat check")
    assert "$ARGUMENTS" in body


def test_the_command_is_thin():
    _, body, text = split(COMMAND)
    assert len(text.splitlines()) <= 40 and len(words(body)) <= 450


def test_the_command_points_to_the_criteria_and_embeds_none_of_it():
    _, body, text = split(COMMAND)
    assert "docs/specs/moat-criteria.md" in body
    assert not shingles(text) & shingles(CRITERIA.read_text()), "six consecutive words of the criteria appear in the command"
    for phrase in ("brand_monopoly", "switching_costs", "tripwire", "observed_damage", "Level 1", "cited fact", "proof_basis", "evidence_confidence"):
        assert phrase not in text


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_the_command_never_names_a_stored_rating_or_where_to_find_one(forbidden):
    assert forbidden.lower() not in COMMAND.read_text().lower()


def test_the_command_names_the_agent_types_and_never_forks():
    _, body, text = split(COMMAND)
    assert "moat-pass-1" in body and "moat-pass-2" in body
    assert "never as a fork" in body
    assert "moat_check_prepare" in body and "moat_check_save" in body and "moat_check_finish" in body
    assert "subagent_type" not in text.lower() or "moat-pass" in text


def test_the_command_only_allows_the_three_helpers_and_the_two_agents():
    front, _, _ = split(COMMAND)
    allowed = [a.strip() for a in front["allowed-tools"].split(",")]
    assert sorted(allowed) == sorted(
        [
            "Bash(uv run --directory backend python -m pipeline.moat_check_prepare *)",
            "Bash(uv run --directory backend python -m pipeline.moat_check_save *)",
            "Bash(uv run --directory backend python -m pipeline.moat_check_finish *)",
            "Agent(moat-pass-1)",
            "Agent(moat-pass-2)",
        ]
    )


def test_every_helper_command_the_command_runs_uses_the_directory_form():
    _, body, _ = split(COMMAND)
    runs = re.findall(r"`(uv run[^`]*)`", body)
    assert runs and all(r.startswith("uv run --directory backend python -m pipeline.moat_check_") for r in runs)


def test_the_command_hands_the_passes_the_dates_it_computed_not_one_for_them_to_work_out():
    _, body, _ = split(COMMAND)
    assert "RUN_DATE: <run_date>" in body and "Stale cutoff: data periods ending before <stale_cutoff>" in body


def test_the_command_retries_only_the_failing_pass_once_and_keeps_the_folder_on_failure():
    _, body, _ = split(COMMAND)
    assert 'start with "pass 1:" or "pass 2:"' in body and "only the pass(es) named, once" in body
    assert "keep `run_dir`" in body


# --- the agents ------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2])
def test_the_agent_has_exactly_the_planned_tools_model_and_flags(n):
    front, _, _ = split(AGENTS[n])
    assert front["name"] == f"moat-pass-{n}" == AGENTS[n].stem
    assert front["tools"] == "Read, Write, WebSearch, WebFetch, ToolSearch"
    assert front["model"] == "sonnet"
    assert front["omitClaudeMd"] is True
    assert "disallowedTools" not in front and "permissionMode" not in front


@pytest.mark.parametrize("n", [1, 2])
def test_the_agent_has_no_shell_search_or_agent_tool(n):
    front, _, _ = split(AGENTS[n])
    tools = {t.strip() for t in front["tools"].split(",")}
    assert not tools & {"Bash", "Grep", "Glob", "Edit", "MultiEdit", "NotebookEdit", "Agent", "Task", "TodoWrite", "PowerShell"}
    assert not any(t.startswith("mcp__") for t in tools)


@pytest.mark.parametrize("n", [1, 2])
def test_the_agent_wires_the_guard_for_every_tool_with_its_own_pass_number(n):
    front, _, _ = split(AGENTS[n])
    hooks = front["hooks"]
    assert list(hooks) == ["PreToolUse"] and len(hooks["PreToolUse"]) == 1
    entry = hooks["PreToolUse"][0]
    assert entry["matcher"] == "*"
    assert len(entry["hooks"]) == 1 and entry["hooks"][0]["type"] == "command"
    assert entry["hooks"][0]["command"] == f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/moat-pass-guard.py" {n}'
    assert GUARD.exists()


def test_the_two_agent_files_differ_only_in_the_pass_number():
    def neutral(text: str) -> str:
        return re.sub(r'moat-pass-[12]\b|pass [12]\b|\\" [12]"', lambda m: m.group(0)[:-2] + "N" + m.group(0)[-1:] if m.group(0).endswith('"') else m.group(0)[:-1] + "N", text)

    one, two = AGENTS[1].read_text(), AGENTS[2].read_text()
    assert one != two and neutral(one) == neutral(two)
    assert [i for i, (x, y) in enumerate(zip(one.splitlines(), two.splitlines())) if x != y] == [1, 2, 11]  # name, description, hook command


@pytest.mark.parametrize("n", [1, 2])
@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_the_agent_never_names_a_stored_rating_or_where_to_find_one(n, forbidden):
    assert forbidden.lower() not in AGENTS[n].read_text().lower()


@pytest.mark.parametrize("n", [1, 2])
def test_the_agent_prompt_is_short_and_embeds_none_of_the_criteria(n):
    _, body, text = split(AGENTS[n])
    assert len(words(body)) <= 150
    assert not shingles(text) & shingles(CRITERIA.read_text())


@pytest.mark.parametrize("n", [1, 2])
def test_the_agent_prompt_names_only_its_folder_files(n):
    _, body, _ = split(AGENTS[n])
    assert "criteria.md" in body and "block.json" in body and "out.json" in body
    assert "/home" not in body and "backend" not in body and "docs/" not in body


def test_the_settings_file_that_is_committed_has_no_moat_check_permission_or_hook():
    """Personal allow rules live in the gitignored settings.local.json; the committed settings.json must not carry them."""
    assert "moat" not in (REPO / ".claude" / "settings.json").read_text().lower()


def test_the_guard_is_executable_python_with_a_shebang():
    text = GUARD.read_text()
    assert text.startswith("#!/usr/bin/env python3")
    compile(text, str(GUARD), "exec")
