"""Neutralisation for the watchlist export files (docs/specs/watchlist-export.md, "Export safety").

A watchlist ticker reaches the API only through the ticker validator (core/tickers.py), so a stored symbol is already a
plain symbol; this is the second layer, applied where the files are written, so a row that predates the validator (or a
hand-edited one) still cannot inject a spreadsheet formula or split a line. The frontend builders
(frontend/lib/watchlistExport.ts) apply the same rules to the files they write.

* thinkorswim .csv, one symbol per line: control characters, whitespace, commas and double quotes are removed (a symbol
  can never end its line or open a second cell), and a symbol that then starts with =, +, - or @ gets a leading single
  quote, the standard defusal for a spreadsheet formula. Only the first character is looked at, so BRK-B and ^GSPC export
  unchanged. The validator forbids a leading "-", and "^" is not a formula character, so no legitimate symbol is touched.
* A symbol that is empty after cleaning is left out of the file.
"""

import re

_UNSAFE = re.compile(r"[\s\x00-\x1f\x7f,\"]")
FORMULA_LEADERS = ("=", "+", "-", "@")


def neutralise_csv_symbol(raw: str) -> str:
    """The symbol as it may be written on a CSV line, or "" when nothing is left of it."""
    cleaned = _UNSAFE.sub("", raw)
    if cleaned.startswith(FORMULA_LEADERS):
        return "'" + cleaned
    return cleaned


def thinkorswim_csv(symbols: list[str]) -> str:
    """Bare symbols, one per line, no header; each line neutralised (see module docstring)."""
    lines = [neutralise_csv_symbol(s) for s in symbols]
    return "".join(f"{line}\n" for line in lines if line)
