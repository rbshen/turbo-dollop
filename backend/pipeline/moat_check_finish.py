"""Deletes one finished (or abandoned) independent Moat check run folder.

    cd backend && uv run python -m pipeline.moat_check_finish <run_dir>

Refuses anything that is not a run folder DIRECTLY under /tmp/moat-check/: another path, the base folder itself, a file such as guard.log,
a symlink, a path that only looks like it is inside (`..`, a link out). Deleting nothing is not an error for a run folder that is already
gone. Exit codes: 0 removed (or already gone); 2 refused."""

import shutil
import sys
from pathlib import Path

from pipeline.moat_check_prepare import BASE_DIR


class FinishRefused(Exception):
    """The path is not a removable run folder."""


def finish(run_dir: str | Path, base: Path = BASE_DIR) -> bool:
    """Removes the run folder; True if something was removed, False if it was already gone. Raises FinishRefused."""
    text = str(run_dir)
    if not text.strip() or "\x00" in text:
        raise FinishRefused("empty or invalid path")
    path = Path(text)
    if not path.is_absolute():
        raise FinishRefused(f"{text!r} is not an absolute path")
    real_base = base.resolve()
    if path.is_symlink():
        raise FinishRefused(f"{text!r} is a symlink")
    real = path.resolve()
    if real.parent != real_base:
        raise FinishRefused(f"{text!r} is not a run folder directly under {real_base}")
    if path.parent.resolve() != real_base or path.name != real.name:
        raise FinishRefused(f"{text!r} does not name a run folder under {real_base}")
    if not real.exists():
        return False
    if not real.is_dir():
        raise FinishRefused(f"{text!r} is not a folder")
    shutil.rmtree(real)
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m pipeline.moat_check_finish <run_dir>", file=sys.stderr)
        return 2
    try:
        removed = finish(argv[0])
    except FinishRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"removed {argv[0]}" if removed else f"{argv[0]} was already gone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
