"""Read-only report on the nightly universes (data/tracked_universe.py): the stock side and the ETF side (since the
2026-10-03 cutover they are disjoint): how many known tickers are in and out, by reason (delisted, index, watchlist,
system, manual, added | browsed, expired, untracked), the TickerView dates, the EXPIRED tickers (idle past 30 days: the
wipe's candidates, with delisted ones listed separately) and which browsed tickers become expired in the next N days.
Makes no FMP call and writes nothing (it does not even call init_db), so it is safe to run anytime.

    uv run python -m pipeline.tracked_universe_report
    uv run python -m pipeline.tracked_universe_report --days 14
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import inspect
from sqlmodel import Session, select

from core.db import engine
from core.models import TickerView
from data.tracked_universe import (
    OUT_OF_UNIVERSE,
    TRACKED_VIEW_WINDOW_DAYS,
    classify_etf_tickers,
    classify_known_tickers,
    load_all_known_tickers,
)


def build_report(session: Session, now: datetime | None = None, within_days: int = 7) -> dict:
    now = now or datetime.now()
    reasons = classify_known_tickers(session, now)
    views = {row.ticker: row.last_viewed_at for row in session.exec(select(TickerView)).all()}
    expiry = {t: views[t] + timedelta(days=TRACKED_VIEW_WINDOW_DAYS) for t, reason in reasons.items() if reason == "browsed"}
    horizon = now + timedelta(days=within_days)
    etf_reasons = classify_etf_tickers(session, now)
    etf_expiry = {t: views[t] + timedelta(days=TRACKED_VIEW_WINDOW_DAYS) for t, reason in etf_reasons.items() if reason == "browsed"}
    return {
        "etf": {
            "known": len(etf_reasons),
            "in_universe": sum(1 for r in etf_reasons.values() if r not in OUT_OF_UNIVERSE),
            "by_reason": dict(Counter(etf_reasons.values())),
            "expiring": sorted((t, d) for t, d in etf_expiry.items() if d <= horizon),
            "delisted": sorted(t for t, r in etf_reasons.items() if r == "delisted"),
            "expired": sorted(t for t, r in etf_reasons.items() if r == "expired"),
        },
        "known": len(load_all_known_tickers(session)),
        "known_stock": len(reasons),
        "in_universe": sum(1 for r in reasons.values() if r not in OUT_OF_UNIVERSE),
        "by_reason": dict(Counter(reasons.values())),
        "ticker_view_rows": len(views),
        "first_view": min(views.values()) if views else None,
        "last_view": max(views.values()) if views else None,
        "expiring": sorted((t, d) for t, d in expiry.items() if d <= horizon),
        "within_days": within_days,
        "delisted": sorted(t for t, r in reasons.items() if r == "delisted"),
        "expired": sorted(t for t, r in reasons.items() if r == "expired"),
    }


def format_report(report: dict) -> str:
    lines = [
        f"Known tickers: {report['known']} ({report['known_stock']} stocks, {report['etf']['known']} ETFs); "
        f"in the stock nightly universe: {report['in_universe']}",
        "By reason: " + ", ".join(f"{k} {v}" for k, v in sorted(report["by_reason"].items())),
        f"TickerView rows: {report['ticker_view_rows']}"
        + (f" (first {report['first_view']:%Y-%m-%d %H:%M}, last {report['last_view']:%Y-%m-%d %H:%M})" if report["ticker_view_rows"] else ""),
        f"Delisted-flagged (excluded): {', '.join(report['delisted']) or 'none'}",
        f"Expired (browsed, idle over {TRACKED_VIEW_WINDOW_DAYS} days, awaiting the wipe): {', '.join(report['expired']) or 'none'}",
        f"Browsed tickers becoming expired within {report['within_days']} days: "
        + (", ".join(f"{t} ({d:%Y-%m-%d})" for t, d in report["expiring"]) or "none"),
    ]
    etf = report["etf"]
    lines += [
        f"ETF side: {etf['known']} known, {etf['in_universe']} in the ETF universe (refreshed by nightly_etf_screener); "
        "by reason: " + ", ".join(f"{k} {v}" for k, v in sorted(etf["by_reason"].items())),
        f"ETF delisted-flagged (excluded): {', '.join(etf['delisted']) or 'none'}",
        f"ETF expired (browsed, idle over {TRACKED_VIEW_WINDOW_DAYS} days, awaiting the wipe): {', '.join(etf['expired']) or 'none'}",
        f"Browsed ETFs becoming expired within {report['within_days']} days: "
        + (", ".join(f"{t} ({d:%Y-%m-%d})" for t, d in etf["expiring"]) or "none"),
    ]
    return "\n".join(lines)


def main(within_days: int = 7) -> dict:
    if not inspect(engine).has_table("tickerview"):
        print("TickerView table does not exist yet: the backend has not started on the new code.")
        return {}
    with Session(engine) as session:
        report = build_report(session, within_days=within_days)
    print(format_report(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only report on the nightly ticker universe.")
    parser.add_argument("--days", type=int, default=7, help="List browsed tickers that become expired within this many days.")
    main(parser.parse_args().days)
