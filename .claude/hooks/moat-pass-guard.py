#!/usr/bin/env python3
"""PreToolUse guard for the blind research passes of the independent Moat check (docs/specs/moat-check.md, "Enforcement").

    python3 moat-pass-guard.py <pass number 1|2>        # the hook payload (JSON) arrives on stdin

Wired in the frontmatter of .claude/agents/moat-pass-1.md and moat-pass-2.md, so it runs for every tool call a pass makes. It FAILS CLOSED:
exit 2 (Claude Code's "block this call") for anything it does not positively recognise, and for any crash. (Any other non-zero exit is a
non-blocking error in Claude Code and the call would go ahead, so every code path below ends in 0 or 2.)

What a pass may do:
  * Read  criteria.md, block.json or out.json in ITS OWN folder, /tmp/moat-check/<run>/pass<n>/  (nothing else on disk: not the repo, not the
    database, not the other pass's folder). Paths are resolved with realpath first, so `..` and symlinks cannot escape; relative paths are denied.
  * Write out.json in its own folder, and nothing else.
  * WebSearch and ToolSearch.
  * WebFetch an http(s) URL on port 80 or 443 whose host is a dotted public-looking NAME. Denied: file: and every other scheme, localhost,
    names without a dot, IP literals in any spelling (127.0.0.1, 127.1, 0x7f000001, 2130706433, [::1]), *.local / *.localhost / *.internal /
    *.lan / *.home / *.corp / *.intranet, user@ in the URL, and any other port. (The app listens on 0.0.0.0:8002 and answers
    /api/tickers/<t>/moat, so the local network is the one place the set rating could be fetched from.) A hostname that DNS-resolves to this
    machine is NOT caught: a residual risk accepted in docs/decisions.md.
  * Every other tool is denied.

Every decision is appended to /tmp/moat-check/guard.log (capped at about 1 MB) so a run can be audited afterwards. The environment variable
MOAT_GUARD_LOG_DIR moves ONLY that log (the tests use it); it cannot widen what a pass may read, and a pass has no way to set it.
"""

import json
import os
import re
import socket
import sys
import time
from urllib.parse import urlsplit

BASE = "/tmp/moat-check"
LOG_NAME = "guard.log"
LOG_CAP_BYTES = 1_000_000
LOG_KEEP_BYTES = 500_000

READ_NAMES = ("criteria.md", "block.json", "out.json")
WRITE_NAMES = ("out.json",)
BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet", ".localdomain")


def _inside_pass_folder(path: str, pass_number: str, names: tuple, base: str) -> tuple:
    """(True, "") when `path` is absolute and, once fully resolved, is one of `names` directly inside <base>/<run>/pass<n>/."""
    if not isinstance(path, str) or not path.strip():
        return False, "empty path"
    if "\x00" in path:
        return False, "NUL in path"
    if not os.path.isabs(path):
        return False, "relative path"
    real_base = os.path.realpath(base)
    real = os.path.realpath(path)
    try:
        relative = os.path.relpath(real, real_base)
    except ValueError:
        return False, "not under the moat-check folder"
    parts = relative.split(os.sep)
    if relative.startswith("..") or len(parts) != 3:
        return False, "not a file in a pass folder under the moat-check folder"
    run, folder, name = parts
    if not run or run.startswith("."):
        return False, "bad run folder"
    if folder != "pass" + pass_number:
        return False, "another pass's folder" if re.fullmatch(r"pass\d+", folder) else "not a pass folder"
    if name not in names:
        return False, "file name not allowed (" + name + ")"
    return True, ""


def check_url(url) -> tuple:
    """(True, "") for an http(s) URL on a dotted public-looking host name and port 80/443; otherwise (False, reason)."""
    if not isinstance(url, str) or not url.strip():
        return False, "empty url"
    url = url.strip()
    if any(ch in url for ch in "\x00\r\n\t "):
        return False, "whitespace or control character in url"
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        return False, "unparseable url"
    if parts.scheme.lower() not in ("http", "https"):
        return False, "scheme " + (parts.scheme or "(none)") + " not allowed"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return False, "credentials or '@' in url"
    if not host:
        return False, "no host"
    host = host.rstrip(".").lower()
    if port not in (None, 80, 443):
        return False, "port " + str(port) + " not allowed"
    if "." not in host:
        return False, "host without a dot (localhost or a bare name)"
    if host.endswith(BLOCKED_HOST_SUFFIXES):
        return False, "local-network host name"
    if ":" in host or host.startswith("["):
        return False, "IPv6 literal"
    try:
        socket.inet_aton(host)  # accepts 127.1, 0x7f.1, octal and decimal forms too
        return False, "IP literal"
    except OSError:
        pass
    if re.fullmatch(r"[0-9x.]+", host) or re.fullmatch(r"0x[0-9a-f]+", host):
        return False, "numeric host"
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", host):
        return False, "unusual host name"
    return True, ""


def decide(payload, pass_number: str, base: str = BASE) -> tuple:
    """(allowed, reason, detail) for one hook payload. Pure apart from reading the filesystem to resolve links."""
    if pass_number not in ("1", "2"):
        return False, "bad pass number", ""
    if not isinstance(payload, dict):
        return False, "payload is not an object", ""
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return False, "payload has no tool_name / tool_input", str(tool)[:80]
    if tool == "Read":
        path = tool_input.get("file_path")
        ok, why = _inside_pass_folder(path, pass_number, READ_NAMES, base)
        return ok, why, str(path)[:200]
    if tool == "Write":
        path = tool_input.get("file_path")
        ok, why = _inside_pass_folder(path, pass_number, WRITE_NAMES, base)
        return ok, why, str(path)[:200]
    if tool == "WebFetch":
        url = tool_input.get("url")
        ok, why = check_url(url)
        return ok, why, str(url)[:200]
    if tool in ("WebSearch", "ToolSearch"):
        return True, "", str(tool_input.get("query", ""))[:120]
    return False, "tool not allowed", tool[:80]


def _log(base: str, pass_number: str, payload, allowed: bool, reason: str, detail: str) -> None:
    """Best effort: a logging failure never changes the decision."""
    try:
        os.makedirs(base, mode=0o700, exist_ok=True)
        path = os.path.join(base, LOG_NAME)
        try:
            if os.path.getsize(path) > LOG_CAP_BYTES:
                with open(path, "rb") as fh:
                    fh.seek(-LOG_KEEP_BYTES, os.SEEK_END)
                    tail = fh.read()
                tail = tail[tail.find(b"\n") + 1 :]
                with open(path, "wb") as fh:
                    fh.write(tail)
        except OSError:
            pass
        agent = payload.get("agent_id", "") if isinstance(payload, dict) else ""
        tool = payload.get("tool_name", "") if isinstance(payload, dict) else ""
        line = "%s pass%s %s %s %s %s agent=%s\n" % (
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            pass_number,
            "ALLOW" if allowed else "DENY ",
            tool,
            detail.replace("\n", " "),
            "" if allowed else "(" + reason + ")",
            agent,
        )
        with open(path, "a") as fh:
            fh.write(line)
    except Exception:
        pass


def main(argv=None, stdin=None, stderr=None, base: str = BASE) -> int:
    argv = sys.argv[1:] if argv is None else argv
    stdin = sys.stdin if stdin is None else stdin
    stderr = sys.stderr if stderr is None else stderr
    pass_number = argv[0] if argv else ""
    payload = None
    try:
        payload = json.loads(stdin.read())
        allowed, reason, detail = decide(payload, pass_number, base)
    except Exception as exc:  # malformed JSON, anything unexpected: block
        allowed, reason, detail = False, "guard error: " + type(exc).__name__, ""
    _log(os.environ.get("MOAT_GUARD_LOG_DIR") or base, pass_number, payload, allowed, reason, detail)
    if allowed:
        return 0
    stderr.write("Blocked by the Moat check guard (" + reason + "). This pass may read only criteria.md, block.json and out.json in its own "
                 "folder, write only out.json there, and use the web (http/https on public host names). Nothing else is available.\n")
    return 2


if __name__ == "__main__":
    try:
        code = main()
    except BaseException:  # never fall through to a non-blocking exit code
        code = 2
    sys.exit(code)
