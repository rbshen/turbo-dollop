"""Read-only audit of how much history each cache holds, to compare before and after an FMP plan change
(docs/specs/fmp-data-and-bar-cache.md, "History protection"). Makes no FMP call and writes nothing: the CLI opens
the database file with SQLite's `mode=ro` (a write would raise), and never calls init_db.

Per cache key it answers "how many tickers hold N periods, and what is the oldest period":

  * FundamentalsCache history keys (core/history_merge.py::HISTORY_KEYS): the histogram of periods held per ticker
    (0 = an empty/unusable row), and the oldest period date (min / median / max, and tickers per oldest year);
  * SharedBarsCache "1d" and "60m", LongHistoryBars: bars held per ticker and the span in years, oldest bar;
  * CorporateEvent per event type: rows per ticker and the oldest event.

    uv run python -m pipeline.cache_history_audit
    uv run python -m pipeline.cache_history_audit --json > before.json     # then again after, and diff the two
    uv run python -m pipeline.cache_history_audit --db /path/to/copy.db
"""

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlmodel import Session, select

from core.history_merge import HISTORY_KEYS
from core.models import CorporateEvent, FundamentalsCache, LongHistoryBars, SharedBarsCache


def _periods_and_oldest(raw_json: str) -> tuple[int, str | None]:
    try:
        data = json.loads(raw_json)
    except ValueError:
        return 0, None
    if not isinstance(data, list):
        return 0, None
    dates = [r["date"][:10] for r in data if isinstance(r, dict) and isinstance(r.get("date"), str) and len(r["date"]) >= 10]
    return len(data), min(dates) if dates else None


def _fundamentals_key(session: Session, statement_type: str, period: str) -> dict | None:
    counts: Counter[int] = Counter()
    oldest: list[str] = []
    rows = session.exec(
        select(FundamentalsCache.raw_json).where(
            FundamentalsCache.statement_type == statement_type, FundamentalsCache.period == period
        )
    )
    for raw_json in rows:
        n, first = _periods_and_oldest(raw_json)
        counts[n] += 1
        if first:
            oldest.append(first)
    if not counts:
        return None
    return {
        "tickers": sum(counts.values()),
        "periods_held": {str(n): counts[n] for n in sorted(counts, reverse=True)},
        "oldest_period": _spread(oldest),
        "tickers_by_oldest_year": dict(sorted(Counter(d[:4] for d in oldest).items())),
    }


def _spread(values: list[str]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {"min": ordered[0], "median": ordered[len(ordered) // 2], "max": ordered[-1]}


def _span_rows(rows: list[tuple]) -> dict | None:
    """rows: (ticker, count, first, last) -> bars/span summary."""
    if not rows:
        return None
    counts = [r[1] for r in rows]
    spans = [round((r[3] - r[2]).days / 365.25, 2) for r in rows]
    firsts = [r[2].strftime("%Y-%m-%d") for r in rows]
    return {
        "tickers": len(rows),
        "bars_per_ticker": {"min": min(counts), "median": int(statistics.median(counts)), "max": max(counts)},
        "span_years": {"min": min(spans), "median": round(statistics.median(spans), 2), "max": max(spans)},
        "oldest_bar": _spread(firsts),
        "tickers_by_span_years": dict(sorted(Counter(str(int(round(s))) for s in spans).items(), key=lambda kv: int(kv[0]))),
    }


def build_audit(session: Session) -> dict:
    fundamentals = {}
    for statement_type, period in sorted(HISTORY_KEYS):
        entry = _fundamentals_key(session, statement_type, period)
        if entry:
            fundamentals[f"{statement_type}/{period}"] = entry

    bars = {}
    for interval in ("1d", "60m"):
        rows = session.exec(
            select(SharedBarsCache.ticker, func.count(), func.min(SharedBarsCache.bar_time), func.max(SharedBarsCache.bar_time))
            .where(SharedBarsCache.interval == interval)
            .group_by(SharedBarsCache.ticker)
        ).all()
        if rows:
            bars[f"shared_bars_cache/{interval}"] = _span_rows([tuple(r) for r in rows])
    long_rows = session.exec(
        select(LongHistoryBars.ticker, func.count(), func.min(LongHistoryBars.bar_time), func.max(LongHistoryBars.bar_time)).group_by(
            LongHistoryBars.ticker
        )
    ).all()
    if long_rows:
        bars["long_history_bars"] = _span_rows([tuple(r) for r in long_rows])

    events = {}
    for event_type in ("earnings", "dividend", "split"):
        rows = session.exec(
            select(CorporateEvent.ticker, func.count(), func.min(CorporateEvent.event_date))
            .where(CorporateEvent.event_type == event_type)
            .group_by(CorporateEvent.ticker)
        ).all()
        if rows:
            events[f"corporate_event/{event_type}"] = {
                "tickers": len(rows),
                "rows_held": {str(n): c for n, c in sorted(Counter(r[1] for r in rows).items(), reverse=True)},
                "oldest_event": _spread([r[2].isoformat() for r in rows]),
            }
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "fundamentals": fundamentals, "bars": bars, "events": events}


def format_audit(audit: dict) -> str:
    lines = [f"Cache history audit ({audit['generated_at']}) -- read-only"]
    lines.append("")
    lines.append("FundamentalsCache history keys: tickers per number of periods held, oldest period")
    for key, e in audit["fundamentals"].items():
        held = ", ".join(f"{n}p x{c}" for n, c in e["periods_held"].items())
        o = e["oldest_period"]
        lines.append(f"  {key:<46} {e['tickers']:>4} tickers | {held}")
        if o:
            by_year = ", ".join(f"{y}: {c}" for y, c in e["tickers_by_oldest_year"].items())
            lines.append(f"  {'':<46} oldest min {o['min']} / median {o['median']} / max {o['max']} | by year {by_year}")
    lines.append("")
    lines.append("Bars (per ticker: bars held, span in years)")
    for key, e in audit["bars"].items():
        b, s, o = e["bars_per_ticker"], e["span_years"], e["oldest_bar"]
        lines.append(
            f"  {key:<46} {e['tickers']:>4} tickers | bars min/median/max {b['min']}/{b['median']}/{b['max']} | span {s['min']}/{s['median']}/{s['max']}y"
            f" | oldest bar {o['min']} .. {o['max']}"
        )
    lines.append("")
    lines.append("Corporate events (rows per ticker, oldest event)")
    for key, e in audit["events"].items():
        held = ", ".join(f"{n} rows x{c}" for n, c in list(e["rows_held"].items())[:6])
        lines.append(f"  {key:<46} {e['tickers']:>4} tickers | {held} | oldest {e['oldest_event']['min']} .. {e['oldest_event']['max']}")
    return "\n".join(lines)


def read_only_engine(db_path: Path):
    return create_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only cache history depth audit.")
    parser.add_argument("--json", action="store_true", help="Print JSON (for diffing before/after) instead of text.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite file to read (default: the app database).")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.db is None:
        from core.db import DB_PATH

        args.db = DB_PATH
    with Session(read_only_engine(args.db.resolve())) as session:
        result = build_audit(session)
    print(json.dumps(result, indent=1) if args.json else format_audit(result))
