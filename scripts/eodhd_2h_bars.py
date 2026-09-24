#!/usr/bin/env python3
"""Fetch the last completed US regular session from EODHD and aggregate it
into 2-hour bars anchored at the 09:30 ET open (Thinkorswim-style).

Usage:
    python3 scripts/eodhd_2h_bars.py [TICKER.US]

Reads the API key from an EOD_API_KEY or EODHD_API_KEY variable in a .env
file (checked at the repo root, then backend/.env). The key is never
printed -- URLs echoed for debugging mask it as api_token=***.

Frugal by design: makes at most 3 API requests total (1 intraday call,
1 optional retry at a different interval, 1 daily EOD sanity check).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

SESSION_OPEN = (9, 30)
SESSION_CLOSE = (16, 0)

BUCKETS = [
    ((9, 30), (11, 30), 120),
    ((11, 30), (13, 30), 120),
    ((13, 30), (15, 30), 120),
    ((15, 30), (16, 0), 30),
]


def find_env_file() -> Path | None:
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [repo_root / ".env", repo_root / "backend" / ".env"]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_api_key() -> tuple[str, Path]:
    env_path = find_env_file()
    if env_path is None:
        print("ERROR: no .env file found at repo root or backend/.env")
        sys.exit(1)

    key = None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name in ("EOD_API_KEY", "EODHD_API_KEY") and value:
            key = value
            break

    if not key:
        print(f"ERROR: no EOD_API_KEY/EODHD_API_KEY found in {env_path}")
        sys.exit(1)

    return key, env_path


def mask(url: str, key: str) -> str:
    return url.replace(key, "***")


@dataclass
class Bar:
    ts_utc: int
    dt_et: "object"
    open: float
    high: float
    low: float
    close: float
    volume: float


def fetch_intraday(ticker: str, key: str, interval: str, from_unix: int, to_unix: int):
    url = (
        f"https://eodhd.com/api/intraday/{ticker}"
        f"?interval={interval}&fmt=json&from={from_unix}&to={to_unix}&api_token={key}"
    )
    print(f"  GET {mask(url, key)}")
    resp = requests.get(url, timeout=30)
    return resp


def fetch_daily(ticker: str, key: str, date_str: str):
    url = f"https://eodhd.com/api/eod/{ticker}?from={date_str}&to={date_str}&fmt=json&api_token={key}"
    print(f"  GET {mask(url, key)}")
    resp = requests.get(url, timeout=30)
    return resp


def parse_intraday_rows(rows: list[dict]) -> list[Bar]:
    bars = []
    for row in rows:
        ts = row.get("timestamp")
        if ts is None:
            continue
        dt_utc = time.gmtime(ts)
        import datetime

        dt_utc_aware = datetime.datetime(*dt_utc[:6], tzinfo=UTC)
        dt_et = dt_utc_aware.astimezone(EASTERN)
        try:
            bars.append(
                Bar(
                    ts_utc=ts,
                    dt_et=dt_et,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b.ts_utc)
    return bars


def filter_regular_session(bars: list[Bar]) -> list[Bar]:
    out = []
    for b in bars:
        t = (b.dt_et.hour, b.dt_et.minute)
        if (t >= SESSION_OPEN) and (t < SESSION_CLOSE):
            out.append(b)
    return out


def last_complete_session_date(bars: list[Bar]):
    """Return the most recent ET date whose session looks complete
    (has a bar starting at/after 15:59 ET), or None."""
    by_date: dict = {}
    for b in bars:
        d = b.dt_et.date()
        by_date.setdefault(d, []).append(b)

    for d in sorted(by_date.keys(), reverse=True):
        day_bars = by_date[d]
        last_bar_time = max((b.dt_et.hour, b.dt_et.minute) for b in day_bars)
        if last_bar_time >= (15, 59):
            return d, day_bars, False
    if by_date:
        # nothing looked complete -- fall back to the most recent date anyway
        d = sorted(by_date.keys(), reverse=True)[0]
        return d, by_date[d], True
    return None, [], False


def aggregate_2h_buckets(day_bars: list[Bar]):
    results = []
    for (sh, sm), (eh, em), expected in BUCKETS:
        bucket_bars = [
            b for b in day_bars
            if (sh, sm) <= (b.dt_et.hour, b.dt_et.minute) < (eh, em)
        ]
        if not bucket_bars:
            results.append(
                {
                    "start": f"{sh:02d}:{sm:02d}",
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "volume": 0.0,
                    "count": 0,
                    "expected": expected,
                }
            )
            continue
        results.append(
            {
                "start": f"{sh:02d}:{sm:02d}",
                "open": bucket_bars[0].open,
                "high": max(b.high for b in bucket_bars),
                "low": min(b.low for b in bucket_bars),
                "close": bucket_bars[-1].close,
                "volume": sum(b.volume for b in bucket_bars),
                "count": len(bucket_bars),
                "expected": expected,
            }
        )
    return results


def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL.US"
    key, env_path = load_api_key()
    print(f"Ticker: {ticker}")
    print(f"Env file: {env_path}")

    requests_used = 0

    # STEP 1: intraday access check, ~4 calendar days window
    now_utc = int(time.time())
    from_unix = now_utc - 4 * 24 * 3600

    print("\n[Step 1] Checking intraday access (interval=1m)...")
    interval_used = "1m"
    resp = fetch_intraday(ticker, key, "1m", from_unix, now_utc)
    requests_used += 1

    rows = None
    if resp.status_code == 200:
        try:
            candidate = resp.json()
        except ValueError:
            candidate = None
        if isinstance(candidate, list) and len(candidate) > 0:
            rows = candidate
        else:
            print(f"  1m returned HTTP 200 but empty/invalid body: {str(candidate)[:300]}")
    else:
        print(f"  1m failed: HTTP {resp.status_code} -- {resp.text[:300]}")

    if rows is None:
        # one retry allowed, at 5m, only if 1m looked like an interval problem
        body_text = resp.text[:500] if resp is not None else ""
        looks_interval_related = resp.status_code in (400, 402, 403) or "interval" in body_text.lower()
        if looks_interval_related and requests_used < 3:
            print("\n[Step 1 retry] Trying interval=5m...")
            interval_used = "5m"
            resp2 = fetch_intraday(ticker, key, "5m", from_unix, now_utc)
            requests_used += 1
            if resp2.status_code == 200:
                try:
                    candidate2 = resp2.json()
                except ValueError:
                    candidate2 = None
                if isinstance(candidate2, list) and len(candidate2) > 0:
                    rows = candidate2
                    resp = resp2
                else:
                    print(f"  5m returned HTTP 200 but empty/invalid body: {str(candidate2)[:300]}")
                    resp = resp2
            else:
                print(f"  5m failed: HTTP {resp2.status_code} -- {resp2.text[:300]}")
                resp = resp2

        if rows is None:
            print("\nSTOPPING: intraday access not available.")
            print(f"Final HTTP status: {resp.status_code}")
            print(f"Final response body (truncated): {resp.text[:500]}")
            print(f"API requests used: {requests_used}")
            sys.exit(1)

    print(f"  OK -- interval used: {interval_used}, {len(rows)} raw rows returned")

    # STEP 2: identify last completed regular session
    all_bars = parse_intraday_rows(rows)
    regular_bars = filter_regular_session(all_bars)
    if not regular_bars:
        print("\nSTOPPING: no regular-session bars found in the returned window.")
        sys.exit(1)

    session_date, day_bars, was_partial_fallback = last_complete_session_date(regular_bars)
    if session_date is None:
        print("\nSTOPPING: could not determine a session date.")
        sys.exit(1)

    print(f"\n[Step 2] Last session used: {session_date} (ET)")
    if was_partial_fallback:
        print("  NOTE: latest date looked partial (no bar reaching ~15:59 ET); "
              "no earlier complete date was found in the fetch window either -- "
              "using this date anyway and flagging it as partial.")

    # STEP 3: aggregate to 2h buckets
    buckets = aggregate_2h_buckets(day_bars)

    print("\n[Step 3] 2-hour bars (anchored 09:30 ET):")
    header = f"{'Bucket start':<14}{'Open':>10}{'High':>10}{'Low':>10}{'Close':>10}{'Volume':>14}{'Bars used/exp':>16}"
    print(header)
    for b in buckets:
        count_str = f"{b['count']}/{b['expected']}"
        if b["count"] == 0:
            print(f"{b['start']:<14}{'--':>10}{'--':>10}{'--':>10}{'--':>10}{'--':>14}{count_str:>16}")
        else:
            print(
                f"{b['start']:<14}{b['open']:>10.2f}{b['high']:>10.2f}{b['low']:>10.2f}"
                f"{b['close']:>10.2f}{b['volume']:>14.0f}{count_str:>16}"
            )

    # STEP 4: sanity-check volume against daily EOD bar
    print("\n[Step 4] Daily EOD sanity check...")
    date_str = session_date.isoformat()
    daily_row = None
    if requests_used < 3:
        try:
            daily_resp = fetch_daily(ticker, key, date_str)
            requests_used += 1
            if daily_resp.status_code == 200:
                daily_json = daily_resp.json()
                if isinstance(daily_json, list) and len(daily_json) > 0:
                    daily_row = daily_json[0]
                else:
                    print(f"  Daily EOD returned empty/invalid body: {str(daily_json)[:300]}")
            else:
                print(f"  Daily EOD failed: HTTP {daily_resp.status_code} -- {daily_resp.text[:300]}")
        except requests.RequestException as exc:
            print(f"  Daily EOD request raised an exception: {exc}")
    else:
        print("  Skipping -- already at the 3-request budget.")

    sum_2h_volume = sum(b["volume"] for b in buckets)

    if daily_row:
        daily_volume = float(daily_row.get("volume") or 0)
        diff_shares = sum_2h_volume - daily_volume
        diff_pct = (diff_shares / daily_volume * 100) if daily_volume else float("nan")
        print(f"  Sum of 2h bar volumes: {sum_2h_volume:.0f}")
        print(f"  Daily EOD volume:      {daily_volume:.0f}")
        print(f"  Difference: {diff_shares:.0f} shares ({diff_pct:+.3f}%)")

        first_bucket_with_data = next((b for b in buckets if b["count"] > 0), None)
        last_bucket_with_data = next((b for b in reversed(buckets) if b["count"] > 0), None)
        agg_open = first_bucket_with_data["open"] if first_bucket_with_data else None
        agg_high = max((b["high"] for b in buckets if b["count"] > 0), default=None)
        agg_low = min((b["low"] for b in buckets if b["count"] > 0), default=None)
        agg_close = last_bucket_with_data["close"] if last_bucket_with_data else None

        print("\n  OHLC check (daily vs aggregated 2h bars):")
        print(f"    Open:  daily={daily_row.get('open')}  agg={agg_open}")
        print(f"    High:  daily={daily_row.get('high')}  agg={agg_high}")
        print(f"    Low:   daily={daily_row.get('low')}  agg={agg_low}")
        print(f"    Close: daily={daily_row.get('close')}  agg={agg_close}")
    else:
        print("  No daily EOD data available -- skipping volume/OHLC comparison.")

    print(f"\nTotal API requests used: {requests_used}")


if __name__ == "__main__":
    main()
