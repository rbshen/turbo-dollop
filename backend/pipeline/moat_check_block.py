"""Builds the BLIND data block for the independent Moat check (docs/specs/moat-check.md, "The command flow", step 2) and writes it to a file.

    cd backend && uv run python -m pipeline.moat_check_block <ticker> --out <path>

The block is everything a blind pass may be told about the company besides the criteria: ticker, name, sector, industry, annual margins
and a price-chart description. It carries NO Moat rating, no Fathom score and no verdict: the script reads three tables only
(`fundamentalscache` for the cached profile and annual income statement, `longhistorybars` and `sharedbarscache` for bars) and never
queries TickerMoat, TickerScore or MoatCheck. The database is opened `mode=ro`, `init_db` is never called and nothing is written but the
output file. The block's key set is fixed; the cache dates it read (fiscal dates, last bar date) and the margin rule applied are
printed to the screen only, never written into the block.

Margins: net margin only for the lender-like buckets in `net_margin_only` (below); every other company, and any industry not seen before,
gets gross and net margin.

Exit codes: 0 written; 2 refused (no cached profile, a known ETF or fund, no annual income statement with revenue, too few bars)."""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlmodel import Session, select

from core.models import FundamentalsCache, LongHistoryBars, SharedBarsCache
from core.tickers import normalize_ticker

BLOCK_KEYS = ("ticker", "name", "sector", "industry", "margins_note", "annual_margins", "price_chart")

# Net margin ONLY (the block omits gross margin) for these. A bank's, insurer's, broker's or asset manager's "gross profit" is not a
# margin that says anything about pricing power, and FMP still reports one for them, so the choice is made by industry, not by a
# missing field. Matches the FMP `industry` label exactly:
#   - "Banks", "Insurance" and "Asset Management" and every "<family> - <variant>" of them (prefix match, NET_MARGIN_ONLY_PREFIXES);
#   - the other exact labels in NET_MARGIN_ONLY_INDUSTRIES ("Financial - Capital Markets" has no variants).
# Anything else, including an industry never seen before, gets gross and net. To extend: add an exact label to
# NET_MARGIN_ONLY_INDUSTRIES, a family to NET_MARGIN_ONLY_PREFIXES, or a ticker to NET_MARGIN_ONLY_TICKERS.
NET_MARGIN_ONLY_PREFIXES = ("Banks - ", "Insurance - ", "Asset Management - ")
NET_MARGIN_ONLY_INDUSTRIES = frozenset({"Banks", "Insurance", "Financial - Capital Markets", "Asset Management"})
# Card LENDERS inside "Financial - Credit Services", the same industry as the payment networks (V, MA, PYPL), which keep gross and net.
# An industry label cannot tell the two apart, so the lenders are named. A lender's interest income minus interest expense is its
# revenue line, so a gross margin is not meaningful for it.
NET_MARGIN_ONLY_TICKERS = frozenset({"AXP", "COF", "SYF", "DFS", "ALLY"})

LONG_HISTORY_MIN_BARS = 2400  # about 9.5 years of sessions: below this the 5-year shared daily bars are used instead


def net_margin_only(industry: str | None, ticker: str) -> bool:
    if normalize_ticker(ticker) in NET_MARGIN_ONLY_TICKERS:
        return True
    industry = (industry or "").strip()
    return industry in NET_MARGIN_ONLY_INDUSTRIES or industry.startswith(NET_MARGIN_ONLY_PREFIXES)


class BlockRefused(Exception):
    """The block cannot be built for this ticker; the message says why."""


def _cached(session: Session, ticker: str, statement_type: str, period: str) -> Any:
    row = session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker, FundamentalsCache.statement_type == statement_type, FundamentalsCache.period == period
        )
    ).first()
    return None if row is None else json.loads(row.raw_json)


def annual_margins(statements: list[dict], net_only: bool) -> dict[str, dict]:
    """{fiscal year: {gross_margin?, net_margin}} oldest first; a year with no revenue is skipped."""
    margins: dict[str, dict] = {}
    for row in sorted(statements, key=lambda r: r["date"]):
        revenue = row.get("revenue") or 0
        if not revenue:
            continue
        entry: dict[str, Any] = {"net_margin": round(row["netIncome"] / revenue, 3)}
        if not net_only:
            gross = row.get("grossProfit")
            entry = {"gross_margin": round(gross / revenue, 3) if gross is not None else None, **entry}
        margins[str(row["fiscalYear"])] = entry
    return margins


def describe_chart(bar_dates: list[str], closes: list[float], window: str) -> dict:
    """The price-chart block (same wording as the v5.1 test round, so the results stay comparable). `bar_dates` are YYYY-MM-DD, oldest first."""
    years = round((date.fromisoformat(bar_dates[-1]) - date.fromisoformat(bar_dates[0])).days / 365.25, 1)
    multiple = closes[-1] / closes[0]
    cagr = (multiple ** (1 / years) - 1) * 100 if years > 0 else 0.0
    peak, peak_index, max_drawdown, trough = closes[0], 0, 0.0, (0, 0)
    for index, close in enumerate(closes):
        if close > peak:
            peak, peak_index = close, index
        drawdown = close / peak - 1
        if drawdown < max_drawdown:
            max_drawdown, trough = drawdown, (peak_index, index)
    from_high = (closes[-1] / max(closes) - 1) * 100
    cutoff = (date.fromisoformat(bar_dates[-1]) - timedelta(days=365)).isoformat()
    year_ago = [i for i, d in enumerate(bar_dates) if d <= cutoff]
    change = (
        f"Change over the last 12 months: {(closes[-1] / closes[year_ago[-1]] - 1) * 100:+.0f}%."
        if year_ago
        else "Change over the last 12 months: not available (under a year of bars)."
    )
    year_end: dict[str, float] = {}
    for bar_date, close in zip(bar_dates, closes):
        year_end[bar_date[:4]] = round(close, 2)
    description = (
        f"{window} daily bars from {bar_dates[0]} to {bar_dates[-1]} ({years} years): close {closes[0]:.2f} -> {closes[-1]:.2f} "
        f"({multiple:.2f}x, about {cagr:.1f}% a year). Maximum drawdown {max_drawdown * 100:.0f}% "
        f"(peak {bar_dates[trough[0]]} to trough {bar_dates[trough[1]]}). Latest close is {from_high:.0f}% from the all-time high "
        f"close in this window. {change}"
    )
    return {"window": f"{window} daily bars", "years": years, "description": description, "year_end_closes": year_end}


def _bars(session: Session, ticker: str) -> tuple[list[str], list[float], str]:
    rows = session.exec(select(LongHistoryBars.bar_time, LongHistoryBars.close).where(LongHistoryBars.ticker == ticker).order_by(LongHistoryBars.bar_time)).all()
    window = "10-year"
    if len(rows) < LONG_HISTORY_MIN_BARS:
        rows = session.exec(
            select(SharedBarsCache.bar_time, SharedBarsCache.close)
            .where(SharedBarsCache.ticker == ticker, SharedBarsCache.interval == "1d")
            .order_by(SharedBarsCache.bar_time)
        ).all()
        window = "5-year"
    return [r[0].date().isoformat() for r in rows], [r[1] for r in rows], window


def build_block(session: Session, ticker: str) -> tuple[dict, dict]:
    """(the block, the screen-only info). Raises BlockRefused. Reads the three cache tables only."""
    ticker = normalize_ticker(ticker)
    profile = _cached(session, ticker, "profile", "latest")
    profile = profile[0] if isinstance(profile, list) and profile else profile
    if not profile:
        raise BlockRefused(f"{ticker} has no cached profile; open the ticker once so the app caches it")
    if profile.get("isEtf") or profile.get("isFund"):
        raise BlockRefused(f"{ticker} is an ETF or fund; an Economic Moat check does not apply to it")
    statements = _cached(session, ticker, "income_statement", "annual")
    net_only = net_margin_only(profile.get("industry"), ticker)
    margins = annual_margins(statements, net_only) if statements else {}
    if not margins:
        raise BlockRefused(f"{ticker} has no cached annual income statement with revenue")
    bar_dates, closes, window = _bars(session, ticker)
    if len(closes) < 2:
        raise BlockRefused(f"{ticker} has fewer than 2 cached daily bars")
    kind = "net margin" if net_only else "gross and net margin"
    block = {
        "ticker": ticker,
        "name": profile.get("companyName"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "margins_note": f"Annual {kind} from the company's own filings; judge only against this company's own history.",
        "annual_margins": margins,
        "price_chart": describe_chart(bar_dates, closes, window),
    }
    info = {
        "margin_rule": f"{'net margin only' if net_only else 'gross and net margin'} (industry: {profile.get('industry')})",
        "fiscal_dates": sorted(r["date"] for r in statements if r.get("revenue")),
        "last_bar_date": bar_dates[-1],
        "bar_source": f"{window} ({len(closes)} bars)",
    }
    return block, info


def main(argv: list[str] | None = None, db_path: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the blind data block for the independent Moat check.")
    parser.add_argument("ticker")
    parser.add_argument("--out", required=True, type=Path, help="where to write the block JSON")
    args = parser.parse_args(argv)
    if db_path is None:
        from core.db import DB_PATH

        db_path = DB_PATH
    engine = create_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true", connect_args={"check_same_thread": False})
    try:
        with Session(engine) as session:
            block, info = build_block(session, args.ticker)
    except BlockRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    args.out.write_text(json.dumps(block, indent=1))
    fiscal = info["fiscal_dates"]
    print(f"wrote {args.out} for {block['ticker']}")
    print(f"  margins: {info['margin_rule']}")
    print(f"  statement fiscal dates read: {fiscal[0]} to {fiscal[-1]} ({len(fiscal)} years)")
    print(f"  last bar date: {info['last_bar_date']} ({info['bar_source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
