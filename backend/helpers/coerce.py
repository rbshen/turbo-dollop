"""The parse boundary for upstream (FMP) values that flow into typed response models (cleanup batch 2026-10-13, docs/specs/auth.md "Not
changed" and docs/decisions.md).

FMP occasionally answers a field with the wrong type (a number as a string, a null, "N/A", a nested object, NaN). A typed response model
(`beta: float | None`) rejects that with a ValidationError and the whole ticker answers 500; arithmetic on it raises TypeError or, worse,
silently repeats a string. The rule here: **a value of the wrong type degrades that one field to None** and nothing else changes.

* A number is an `int` or `float` that is finite and not a `bool`. A numeric *string* is NOT a number here (the stored form of a field
  is what FMP sent; guessing "1.2" is a number is how "N/A" or "1,2" would slip through some other day).
* Text is a `str`. Anything else is None.

Pure, no DB, no FMP. Scoring never calls this to decide anything: it is applied to the dicts that feed response models, before the
values are read.
"""

import math
from collections.abc import Iterable


def finite_number(value: object) -> float | None:
    """`value` as a finite float, or None (null, a string, a bool, a list, NaN, +-inf)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def text_or_none(value: object) -> str | None:
    """`value` when it is a string, else None. Not stripped or blanked: the text is shown as FMP sent it."""
    return value if isinstance(value, str) else None


def count_or_zero(value: object) -> int:
    """A non-negative whole count (analyst counts), 0 for anything else."""
    number = finite_number(value)
    return int(number) if number is not None and number > 0 else 0


def clean_row(row: dict, numbers: Iterable[str] = (), texts: Iterable[str] = ()) -> dict:
    """A copy of `row` in which every listed key that is PRESENT holds a finite number (numbers) or a string (texts), else None. Keys that
    are absent stay absent (so `row.get(k, default)` behaves as before) and unlisted keys are untouched."""
    out = dict(row)
    for key in numbers:
        if key in out:
            out[key] = finite_number(out[key])
    for key in texts:
        if key in out:
            out[key] = text_or_none(out[key])
    return out
