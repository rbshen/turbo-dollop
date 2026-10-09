# Sector / industry average P/E (FMP) — Phase 1, data layer

Status (2026-10-09): **data layer only.** The table, the 5-year backfill, the nightly snapshot job and a series read
function exist. There is no chart, no overlay and no API route yet, and the ticker's own P/E series is not built.

## What it is, and the label

FMP publishes the **average P/E of the listed companies** in a sector or an industry, per exchange, per trading day.
Any UI must call it exactly **"average PE of listed companies (FMP)"** (`data/sector_industry_pe_data.py::LABEL`).

**Basis caveat.** It is FMP's own aggregate, not Fathom's. Fathom's ticker P/E is trailing: price ÷ TTM EPS from the
cached `ratios/ttm` row, NULL for zero or negative EPS, FMP `priceToEarningsRatioTTM` for ADRs
([overview.md](overview.md), "P/E basis"). FMP does not say how it averages (mean or median, whether loss-makers are
excluded, which EPS). A ticker line and this line are therefore **not like for like**: use the sector/industry series
for its trend and for rough position, never as a precise premium/discount.

**`pe = 0` is a gap, not a P/E.** FMP answers `0` for a day on which a group has no usable positive-earnings average
(2026-10-09 backfill: 14,382 of 373,042 rows, mostly thin AMEX/NASDAQ industries plus
1,046 sector rows on AMEX, 12 on NASDAQ). It is **stored as returned**; a reader must treat `pe <= 0` as no value (and
never plot it as zero). No value is negative or above 1,000.

## Which exchange (rule for the later overlay)

Use the **ticker's own listing exchange**: NASDAQ, NYSE or AMEX (the three FMP exchanges stored). A ticker listed on
OTC, CBOE or anywhere else gets **no overlay**, and **ETFs get none** either (`isEtf`/`isFund`). Fathom is US-listed
only; nothing is stored for any other exchange. A sector or industry with no stored series on that exchange also shows
no overlay (it is never substituted from another exchange).

## Data group `sector_industry_pe`

All four endpoints map to it (`core/data_groups.py::ENDPOINT_GROUP`): `/sector-pe-snapshot`, `/industry-pe-snapshot`,
`/historical-sector-pe`, `/historical-industry-pe`. Label "Sector & industry P/E", listed in Settings > FMP data groups
like every group (the list comes from the API). Probe: `/sector-pe-snapshot?date=2024-01-02&exchange=NASDAQ` (symbol-less,
so the failing call is its own canary).

**Required tier: Starter — best known, UNVERIFIED.** Source: FMP's developer docs pages for these endpoints 403 to our
fetcher (as every FMP docs/pricing page does) and the search results name no plan for them. FMP's pricing page (via
search summary, 2026-10-09) gives Basic and Starter **5 years** of history and Premium/Ultimate **30+ years**, and our
backfill window is exactly 5 years, so Starter is the lowest tier at which the full window should be served. Our key is
Ultimate, so nothing can be tested; the 402 safety net corrects a wrong value at runtime (a canary-confirmed 402 marks the
group `plan_restricted`, re-probed weekly). Edit the tier in Settings if FMP's page says otherwise.

## FMP facts (confirmed live 2026-10-09)

- Snapshots need `date` and `exchange`; historical calls need the sector / industry name and `exchange`. **Omitting
  `exchange` silently defaults to NASDAQ**, so every call passes it.
- **Always pass explicit `from`/`to`** on the historical calls: the default window ends 2024-03-01.
- A snapshot dated on a weekend or in the future still returns data, so the job uses the **last completed trading day**
  (`clients/shared_bars_cache.py::_most_recent_completed_trading_date`, XNYS holiday- and early-close-aware).
- A 5-year historical answer comes back whole (1,279 rows for Technology/NYSE), newest first, no paging.
- Row shape: `{"date", "sector"|"industry", "exchange", "pe"}`. Industry names are FMP's own labels
  ("Software - Application"); the set differs per exchange (2026-10-08 snapshot: 11 sectors on each exchange; industries
  NASDAQ 127, NYSE 128, AMEX 27).

## Table `SectorIndustryPe`

`(id, kind, name, exchange, date, pe)`, `kind` = `sector` | `industry`, unique `(kind, name, exchange, date)`
(`uq_sector_industry_pe_key`). The column is called `date` as specified (the model aliases the type as `date_type`).

**History protection: upsert-only.** The table is outside `FundamentalsCache`, so `HISTORY_KEYS` does not apply; the
equivalent guarantee is that every write is `INSERT ... ON CONFLICT DO UPDATE SET pe` and **nothing deletes**: a
restated value for the same day updates, an empty, shorter, malformed or error answer writes nothing and removes nothing.
No retention prune yet (about 75,000 rows a year).

## Backfill (one time, 5 years)

`uv run python -m pipeline.backfills.backfill_sector_industry_pe [--exchanges NYSE,..] [--kinds sector,..] [--force]`
(real database; not a cron job, no heartbeat). Window: today minus 5 calendar years through the last completed trading
day. For each exchange it reads the two snapshots at the window end to discover the names (the 11 sectors and **every
industry on that exchange's industry snapshot**), then fetches one historical series per name. Paced at 4 calls/s; about
9 minutes for 315 series.

- **Idempotent:** upserts; a second run changes nothing.
- **Resumable:** a series whose oldest stored row is within 14 days of the window start is skipped (`--force` refetches);
  each series is one atomic write, so a crash loses at most the series in flight. Series that genuinely start later
  (31 thin industries on 2026-10-09) are refetched on every run, which is harmless.
- **Empty answer** (`[]`): nothing recorded, logged as a warning, listed in the report, run continues; retried next run.
- **Per-series failure:** logged and listed, run continues; a disabled group (or master switch) stops the run.
- Skipped with a message while the group or the master switch is off.

Run of 2026-10-09: 315 series, 315 fetched, 0 empty, 0 failed; 373,042 rows (industry AMEX 22,007; NASDAQ 148,967;
NYSE 160,288; sector AMEX 13,641; NASDAQ 14,070; NYSE 14,069), 2021-10-11 to 2026-10-08.

## Nightly job `pipeline.nightly_sector_industry_pe`

3:05 AM server time, daily. **The server timezone is UTC** (`timedatectl`: Etc/UTC, checked 2026-10-09), so 3:05 is 11:05 PM US Eastern (10:05 PM during standard time), hours after the 4:00 PM ET close (1:00 PM on an early close), when the day's session is complete. 2 snapshots × 3 exchanges = 6 calls (~8 s) for the last completed trading day, upserted
(a weekend or holiday re-run rewrites the same day). Slot: after the 2:00 fundamentals fetch (worst seen 64.5 min, ends
~3:04) and before the 3:10 price-target snapshot and the 3:25 recompute; nothing depends on it (pinned by
`tests/test_cron_wiring.py`). `cron_heartbeat("pipeline.nightly_sector_industry_pe")`, `CRON_JOB_NAMES`,
`_EXPECTED_CADENCE_HOURS` (36 h) and `JOB_METADATA` entries exist.

- Gate: `job_skip_reason("sector_industry_pe")` → a real `skipped` cron status, zero calls, while the group or master is off.
- One failed call does not stop the others. The run is `failure` when every call failed (`check_failure_threshold`; the
  5%/25 rule cannot apply to 6 calls) or **when it wrote no row at all**; otherwise the message reads
  `N rows for <date>, F of 6 calls failed, D with no data`.
- Log: `backend/logs/nightly_sector_industry_pe.log`.
- **Unverified:** whether FMP has the snapshot for the just-closed session at 3:05 UTC (11:05 PM ET). Verified only for
  an earlier completed day. If it is not published yet the job writes nothing and goes red; moving the slot later (before
  3:25) or asking for the previous session fixes it.

## Reading

`data/sector_industry_pe_data.py::get_series(kind, name, exchange, years=5)` → `[(date, pe), ...]` oldest first
(empty = no overlay). No route yet.
