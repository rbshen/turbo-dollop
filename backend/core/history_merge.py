"""The one merge rule for history-bearing cache writes (2026-10-02, docs/specs/fmp-data-and-bar-cache.md,
"History protection").

A cached statement row is a whole FMP response (a JSON list of period rows, newest first). Writing the next
response over it wholesale loses history whenever the new answer is shorter than the cached one: a plan that
silently clamps `limit=10` to 5, a partial body, an empty `[]` or an error object. `merge_history` is the single
rule every such write goes through (`core/cache.py::_write_cache_row`):

  * a row in the new response replaces the cached row for the SAME period (a restatement still updates);
  * cached rows for periods the new response does not contain are kept, newest first, up to
    max(len(cached), len(new)) rows in total -- the stored history is never shorter than before, and in normal
    operation (a full-length answer) the result is identical to the new response, so the window still rolls;
  * an empty, null, error or non-list body never replaces a non-empty cached row (the cached rows are kept);
  * the row shape is unchanged (a list of the same dicts, newest first), so no reader changes.

A period is identified by the row's `date` (ISO, first 10 chars): every history endpoint cached here returns
one. If either side has a row without a date the rule cannot tell periods apart, so it degrades to the safe
count rule (take the new answer only if it is at least as long as the cached one).

Which cache keys go through the rule is `HISTORY_KEYS` (an allow-list; everything else keeps the plain overwrite).
`HISTORY_STATEMENT_TYPES`/`SNAPSHOT_STATEMENT_TYPES` partition every cached statement type so a new one cannot be
added without deciding which side it is on (tests/test_history_merge.py pins it).

`ClampTracker` is the visibility half: it logs a clamp ONCE per ticker per run and counts it; the nightly
fundamentals job reads the count into its status message. Informational only -- it never fails a job."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# (statement_type, period) pairs whose payload is a list of dated period rows. Limit-1 keys
# (enterprise_values/quarter, financial_growth/annual, ratios/latest) are included: with the
# max(len) cap the rule degenerates to "replace, unless the new body is empty".
HISTORY_KEYS: frozenset[tuple[str, str]] = frozenset(
    {
        ("income_statement", "annual"),
        ("income_statement", "quarterly"),
        ("cash_flow_statement", "annual"),
        ("cash_flow_statement", "quarterly"),
        ("balance_sheet_statement", "annual"),
        ("balance_sheet_statement", "quarterly"),
        ("key_metrics", "annual"),
        ("ratios", "annual_10y"),
        ("ratios", "latest"),
        ("enterprise_values", "quarter"),
        ("financial_growth", "annual"),
        ("financial_statement_full_as_reported", "annual"),
        ("financial_statement_full_as_reported", "quarterly"),
        ("analyst_estimates", "latest"),
        ("grades_historical", "latest"),
        ("revenue_product_segmentation", "annual"),
        ("revenue_geographic_segmentation", "annual"),
    }
)
HISTORY_STATEMENT_TYPES: frozenset[str] = frozenset(t for t, _ in HISTORY_KEYS)

# Every other statement type cached in FundamentalsCache, and why it is deliberately not merged.
SNAPSHOT_STATEMENT_TYPES: frozenset[str] = frozenset(
    {
        "profile", "quote", "price_change", "forex_rate", "etf_info",  # one current snapshot
        "grades_consensus", "price_target_consensus", "price_target_summary", "price_target_news",  # one current snapshot
        "news",  # shelved
        "sec_company_facts",  # SEC EDGAR, not FMP, one blob
        "institutional_ownership_summary", "institutional_ownership_holders",  # one row per quarter label; shelved
        "earnings",  # 8 rows incl. scheduled dates: a rescheduled date would leave a phantom past "report"
        "historical_price_eod",  # short rolling window of bars (header volume), not history
    }
)

# fetched_at stamped on a history row by an explicit refresh: stale to every freshness rule, rows kept.
# core/cache.py::_is_earnings_aware_stale treats it as stale unconditionally; prune_cache leaves it alone.
INVALIDATED_AT = datetime(1970, 1, 1)


def is_history_key(statement_type: str, period: str) -> bool:
    return (statement_type, period) in HISTORY_KEYS


def _period_key(row: object) -> str | None:
    if not isinstance(row, dict):
        return None
    value = row.get("date")
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return None


@dataclass
class HistoryMerge:
    rows: object  # what to store (and return to the caller)
    action: str  # "replace" | "merge" | "kept_cached"
    clamped: bool = False  # fewer periods than cached AND the oldest cached period is older than the oldest returned
    empty_kept: bool = False  # an empty/null/error/non-list body was refused over a non-empty cached row
    cached_count: int = 0
    new_count: int | None = None  # None when the body was not a list
    oldest_cached: str | None = None
    oldest_new: str | None = None


def merge_history(cached: object, new: object) -> HistoryMerge:
    """`cached` is the parsed cached payload (None when there is no row), `new` the fresh response."""
    cached_rows = cached if isinstance(cached, list) else []
    new_is_rows = isinstance(new, list) and len(new) > 0 and all(isinstance(r, dict) for r in new)
    new_count = len(new) if isinstance(new, list) else None

    if not cached_rows:
        return HistoryMerge(rows=new, action="replace", new_count=new_count)  # nothing to protect

    cached_keys = [_period_key(r) for r in cached_rows]
    oldest_cached = min((k for k in cached_keys if k), default=None)
    base = dict(cached_count=len(cached_rows), new_count=new_count, oldest_cached=oldest_cached)

    if not new_is_rows:
        return HistoryMerge(rows=cached_rows, action="kept_cached", empty_kept=True, **base)

    new_keys = [_period_key(r) for r in new]
    oldest_new = min((k for k in new_keys if k), default=None)
    base["oldest_new"] = oldest_new

    if None in cached_keys or None in new_keys:
        # Periods cannot be told apart: the only safe rule is "never shorter".
        if len(new) >= len(cached_rows):
            return HistoryMerge(rows=new, action="replace", **base)
        return HistoryMerge(rows=cached_rows, action="kept_cached", clamped=True, **base)

    replaced = set(new_keys)
    kept = sorted(
        (r for r, k in zip(cached_rows, cached_keys) if k not in replaced), key=_period_key, reverse=True
    )
    room = max(len(cached_rows), len(new)) - len(new)
    carried = kept[:room]
    merged = sorted([*new, *carried], key=_period_key, reverse=True)
    clamped = len(new) < len(cached_rows) and oldest_cached is not None and oldest_new is not None and oldest_cached < oldest_new
    return HistoryMerge(rows=merged, action="merge" if carried else "replace", clamped=clamped, **base)


@dataclass
class ClampTracker:
    """Once-per-ticker-per-run log + count, per store ("fundamentals", "bars"). `reset()` starts a run (the nightly
    fundamentals job calls it first); in a long-lived server process it simply logs the first clamp per ticker."""

    _clamped: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    _empty: dict[str, dict[str, set[str]]] = field(default_factory=dict)

    def reset(self) -> None:
        self._clamped.clear()
        self._empty.clear()

    def record_clamp(self, ticker: str, label: str, message: str, store: str = "fundamentals") -> bool:
        """True when this is the ticker's first clamp this run (and so was logged)."""
        seen = self._clamped.setdefault(store, {}).setdefault(ticker, set())
        first = not seen
        seen.add(label)
        if first:
            logger.warning("History clamped for %s (%s): %s", ticker, label, message)
        return first

    def record_empty_kept(self, ticker: str, label: str, message: str, store: str = "fundamentals") -> bool:
        seen = self._empty.setdefault(store, {}).setdefault(ticker, set())
        first = not seen
        seen.add(label)
        if first:
            logger.warning("Empty/invalid body ignored for %s (%s): %s", ticker, label, message)
        return first

    def clamped_tickers(self, store: str = "fundamentals") -> int:
        return len(self._clamped.get(store, {}))

    def empty_kept_tickers(self, store: str = "fundamentals") -> int:
        return len(self._empty.get(store, {}))


history_clamps = ClampTracker()
