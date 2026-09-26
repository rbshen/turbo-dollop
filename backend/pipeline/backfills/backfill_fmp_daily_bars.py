"""One-time standalone script (FMP Phase 2, 2026-09-24): re-source the "1d"
rows of SharedBarsCache for every US-listed ticker from FMP
(`/historical-price-eod/full`, data group `daily_prices`), REPLACING each
ticker's cached history with a fresh 5-year window.

Why: FMP becomes the primary daily-bar source (clients/daily_bar_sources.py::
FMPWithFallback). The nightly path only appends/overlaps; this script rebuilds
what is already stored on the new basis in one pass -- split- AND spin-off-
adjusted (not dividend-adjusted), stitched symbols (META, B, BNY, COHR, CNSWF,
PARA, SPCX ...) become one continuous series. See
docs/fmp_phase2_daily_prices_plan_2026-09-24.md.

Replace, not merge, per ticker in ONE transaction (delete that ticker's `1d`
rows, insert the FMP frame -- clients/shared_bars_cache.py::_write_rows
replace=True), and only when FMP returns a usable frame: a ticker FMP answers
empty for, or errors on, keeps its existing rows untouched (reported as
"kept"). A ticker whose new history STARTS materially later than the old one
(a young/renamed listing whose cache was stitched -- SPCX) is reported under
"shrunk" so it can be reviewed in the dry run before the real one.

Universe: the union of every daily-bar consumer's own universe (tracked universe, S&P 500,
W1-W5 watchlists, sector ETFs + SPY, Moat-rated), plus every ticker already
holding "1d" rows (^GSPC), routed by LISTING EXCHANGE
(clients/daily_bar_sources.py::route_by_source: NYSE/NASDAQ/AMEX/CBOE/OTC = US;
no profile + no dot = US). Non-US tickers are left on Yahoo, untouched.
Delisted-flagged tickers (TickerScore.delisted_at) are skipped, so e.g. AVB is
left exactly as it is.

The dry run FETCHES from FMP (paced, ~1 call per ticker) but writes nothing:
it reports, per ticker and in aggregate, how the fresh series compares to the
cache -- share of days within 0.1%, days off by more than 1% (excluding the
last bar), dates only one side has -- which is the parity check that gates the
real run.

NON-US (FMP Phase 3, 2026-09-25): `--scope non-us` does the same for every non-US
listing (HKSE today) through the `daily_prices_intl` group, with FMP's phantom
holiday/weekend bars removed first (clients/daily_bar_sources.py::drop_phantom_bars).
It reports the per-ticker phantom-bar drop counts and is GATED: it refuses to
write unless every ticker has >= GATE_MIN_WITHIN_PCT of its shared-date closes
within GATE_TOLERANCE of the cache (a dry run reports the same numbers, plus every
date that differs by more than the tolerance, so each cluster can be traced by
hand before the real run). `--scope us` (default) is the Phase 2 behaviour,
untouched; `--scope all` does both.

Run (writes nothing):
    uv run python -m pipeline.backfills.backfill_fmp_daily_bars --dry-run [--scope us|non-us|all] [--report out.json]
Run for real (take a backup first):
    uv run python -m pipeline.backfills.backfill_fmp_daily_bars [--scope ...]
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import re

import pandas as pd
from sqlmodel import Session, select

from clients.daily_bar_sources import FMPDailySource, route_by_source
from clients.shared_bars_cache import DAILY_INTERVAL, _eastern_today, _load_frames, _write_rows
from core.data_groups import effective_state
from core.db import engine, init_db
from core.logging_config import configure_logging
from core.models import SharedBarsCache, TickerScore
from core.tickers import normalize_ticker
from data.sector_heatmap_data import SECTOR_ETFS
from data.watchlists import list_tickers_across_watchlists
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe, load_sp500_tickers
from pipeline.stale_data_health_check import load_delisted_tickers

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "backfill_fmp_daily_bars.log"

# Covers every daily-bar consumer's own window (Chart D_2Y's 5y is the widest).
LOOKBACK_DAYS = 5 * 365

WATCHLIST_NAME_PATTERN = re.compile(r"^W[1-5]$")
# Same set data/momentum_data.py::MOAT_VALUES uses -- a ticker with no moat set at all is
# excluded, never included with a fabricated default.
MOAT_VALUES = {"wide_moat", "narrow_moat", "no_moat"}


def _resolve_universe(session: Session) -> list[str]:
    """Union of every daily-bar consumer's own universe, deduped and normalized (callers
    route/filter US vs non-US themselves)."""
    tickers: set[str] = set(load_full_tracked_universe(session))
    tickers.update(load_sp500_tickers(session))
    lz_tickers, _ = list_tickers_across_watchlists(session, WATCHLIST_NAME_PATTERN)
    tickers.update(lz_tickers)
    tickers.update(t for t, _ in SECTOR_ETFS)
    tickers.add("SPY")
    moat_rows = session.exec(select(TickerScore.ticker, TickerScore.moat)).all()
    tickers.update(t for t, moat in moat_rows if moat in MOAT_VALUES)
    return sorted(normalize_ticker(t) for t in tickers)

# New history starting more than this many days after the old first bar is
# flagged "shrunk" (reviewed in the dry run).
SHRINK_FLAG_DAYS = 30
# A ticker counts as a >1% mismatch day when its close differs from FMP's by more than this.
MISMATCH_TOLERANCE = 0.01
CLOSE_PARITY_TOLERANCE = 0.001
# Non-US parity gate (P3): every ticker needs >= 99% of its shared-date closes within 0.5%.
GATE_TOLERANCE = 0.005
GATE_MIN_WITHIN_PCT = 99.0

logger = logging.getLogger(__name__)


def _cached_tickers() -> set[str]:
    with Session(engine) as session:
        return set(session.exec(select(SharedBarsCache.ticker).where(SharedBarsCache.interval == DAILY_INTERVAL).distinct()).all())


def compare_to_cache(new: pd.DataFrame, old: pd.DataFrame | None) -> dict:
    """Per-ticker comparison of a fresh FMP frame against the cached one."""
    out = {"new_rows": len(new), "new_first": str(new.index.min().date()), "new_last": str(new.index.max().date())}
    if old is None or old.empty:
        return {**out, "old_rows": 0, "overlap": 0}
    joined = old[["close"]].join(new[["close"]], lsuffix="_old", rsuffix="_new", how="inner")
    rel = (joined["close_old"] / joined["close_new"] - 1).abs()
    last = joined.index.max() if len(joined) else None
    inner = rel.drop(last, errors="ignore")
    return {
        **out,
        "old_rows": len(old),
        "old_first": str(old.index.min().date()),
        "old_last": str(old.index.max().date()),
        "overlap": len(joined),
        "within_0.1pct": int((rel < CLOSE_PARITY_TOLERANCE).sum()),
        "days_off_gt_1pct": int((inner > MISMATCH_TOLERANCE).sum()),
        "max_diff_pct_ex_last": float(inner.max() * 100) if len(inner) else 0.0,
        "within_0.5pct_pct": round(float((rel <= GATE_TOLERANCE).mean() * 100), 3) if len(rel) else None,
        "dates_off_gt_0.5pct": {
            str(d.date()): round(float(v * 100), 3) for d, v in rel[rel > GATE_TOLERANCE].items()
        },
        "last_bar_diff_pct": float(rel.loc[last] * 100) if last is not None else 0.0,
        "cache_only_dates": int((~old.index.isin(new.index)).sum()),
        "fmp_only_dates": int(((~new.index.isin(old.index)) & (new.index >= old.index.min())).sum()),
    }


class ParityGateError(RuntimeError):
    """A non-US ticker failed the parity gate; nothing was written."""


def parity_gate_failures(per_ticker: dict[str, dict]) -> dict[str, float | None]:
    """{ticker: share of shared-date closes within GATE_TOLERANCE} for every ticker
    below GATE_MIN_WITHIN_PCT. A ticker with no cached history has nothing to compare
    against and passes vacuously (reported separately as new_tickers)."""
    return {
        t: c["within_0.5pct_pct"] for t, c in per_ticker.items()
        if c.get("within_0.5pct_pct") is not None and c["within_0.5pct_pct"] < GATE_MIN_WITHIN_PCT
    }


async def main(
    tickers: list[str] | None = None, dry_run: bool = False, report_path: Path | None = None, scope: str = "us"
) -> dict:
    configure_logging(LOG_PATH)
    init_db()
    do_us, do_non_us = scope in ("us", "all"), scope in ("non-us", "all")
    for wanted, group in ((do_us, "daily_prices"), (do_non_us, "daily_prices_intl")):
        live, reason = effective_state(group)
        if wanted and not live:
            raise RuntimeError(f"{group} group is not live ({reason}) -- turn it on before backfilling from FMP")

    with Session(engine) as session:
        universe = tickers if tickers is not None else sorted(set(_resolve_universe(session)) | _cached_tickers())
        delisted = load_delisted_tickers(session)
    universe = [t for t in universe if t not in delisted]
    us, non_us = route_by_source({t: LOOKBACK_DAYS for t in universe})
    logger.info(
        "FMP daily-bar backfill%s (scope %s): %d US-listed ticker(s), %d non-US, %d delisted-flagged skipped.",
        " (DRY RUN)" if dry_run else "", scope, len(us), len(non_us), len(delisted),
    )

    start = time.monotonic()
    replaced: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    wanted_tickers: dict[str, int] = {}
    phantom_dropped: dict[str, int] = {}
    if do_us:
        wanted_tickers.update(us)
        frames.update(
            await FMPDailySource().get_daily_bars(us, False, reference=_eastern_today(), replace_tickers=replaced, full_refresh=True)
        )
    if do_non_us:
        wanted_tickers.update(non_us)
        intl = FMPDailySource(group="daily_prices_intl", non_us=True)
        frames.update(
            await intl.get_daily_bars(non_us, False, reference=_eastern_today(), replace_tickers=replaced, full_refresh=True)
        )
        phantom_dropped = dict(intl.phantom_dropped)
    fetch_seconds = time.monotonic() - start
    kept = sorted(set(wanted_tickers) - set(frames))

    with Session(engine) as session:
        old_frames = _load_frames(session, list(frames), DAILY_INTERVAL, datetime(1990, 1, 1).date())
    per_ticker = {t: compare_to_cache(df, old_frames.get(t)) for t, df in frames.items()}
    shrunk = sorted(
        t for t, c in per_ticker.items()
        if c["old_rows"] and (pd.Timestamp(c["new_first"]) - pd.Timestamp(c["old_first"])).days > SHRINK_FLAG_DAYS
    )
    grown = sorted(
        t for t, c in per_ticker.items()
        if c["old_rows"] and (pd.Timestamp(c["old_first"]) - pd.Timestamp(c["new_first"])).days > SHRINK_FLAG_DAYS
    )
    new_tickers = sorted(t for t, c in per_ticker.items() if not c["old_rows"])

    overlap = sum(c.get("overlap", 0) for c in per_ticker.values())
    within = sum(c.get("within_0.1pct", 0) for c in per_ticker.values())
    summary = {
        "dry_run": dry_run,
        "scope": scope,
        "us_routed": len(us),
        "non_us_routed": len(non_us),
        "delisted_skipped": sorted(delisted),
        "served_by_fmp": len(frames),
        "kept_not_served": kept,
        "days_overlapping": overlap,
        "pct_days_within_0.1pct": round(within / overlap * 100, 3) if overlap else None,
        "tickers_with_days_off_gt_1pct": sorted(t for t, c in per_ticker.items() if c.get("days_off_gt_1pct")),
        "shrunk": shrunk,
        "grown": grown,
        "new_tickers": new_tickers,
        "fetch_seconds": round(fetch_seconds, 1),
        "phantom_bars_dropped": phantom_dropped,
    }
    gate_failures = parity_gate_failures(per_ticker) if do_non_us else {}
    if do_non_us:
        summary["parity_gate_failures"] = gate_failures

    written = 0
    if gate_failures and not dry_run:
        # Write nothing at all -- not even the US half of an `all` run.
        if report_path:
            report_path.write_text(json.dumps({"summary": summary, "per_ticker": per_ticker}, indent=1, default=str))
        raise ParityGateError(f"parity gate failed (nothing written): {gate_failures}")
    if not dry_run:
        fetched_at = datetime.now()
        with Session(engine) as session:
            for i, (ticker, df) in enumerate(frames.items(), start=1):
                _write_rows(session, ticker, DAILY_INTERVAL, df, fetched_at, replace=True)
                written += len(df)
                if i % 100 == 0:
                    logger.info("wrote %d/%d tickers", i, len(frames))
    summary["rows_written"] = written
    summary["duration_seconds"] = round(time.monotonic() - start, 1)
    logger.info("FMP daily-bar backfill complete: %s", {k: v for k, v in summary.items() if k != "delisted_skipped"})
    if report_path:
        report_path.write_text(json.dumps({"summary": summary, "per_ticker": per_ticker}, indent=1, default=str))
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch from FMP and compare against the cache, write nothing")
    parser.add_argument("--scope", choices=("us", "non-us", "all"), default="us", help="which listings to backfill (default: us)")
    parser.add_argument("--tickers", type=str, default=None, help="comma-separated explicit list (testing)")
    parser.add_argument("--report", type=Path, default=None, help="write the per-ticker JSON report here")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    explicit = [normalize_ticker(t) for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    print(json.dumps(asyncio.run(main(explicit, args.dry_run, args.report, args.scope)), indent=1, default=str))
