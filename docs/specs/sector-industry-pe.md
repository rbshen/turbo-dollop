# Sector / industry average P/E (FMP) — Phase 1, data layer

Status (2026-10-09): **phase 1 (data layer) and phase 2 (the P/E history chart) are built.** Phase 1: the table, the 5-year
backfill, the nightly snapshot job and a series read function. Phase 2: the ticker's own P/E series, the route
`GET /api/tickers/{t}/pe-history` and the "P/E history" card on the Ratios tab (below). The table keeps its 5 years; the
chart window is **1 year**.

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

## Which exchange (rule for the overlay)

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
(empty = no overlay). The chart calls it with `years=1`.

## Phase 2: the P/E history chart (Ratios tab)

**Window: the last 1 year** (`data/pe_history_data.py::CHART_WINDOW_YEARS`). The API returns only the last year of stock,
sector and industry points, so all three lines start on the same date; the table still holds 5 years (a longer window
would need no Phase 1 change). Decision of 2026-10-09 (docs/decisions.md).

**Route** `GET /api/tickers/{t}/pe-history` → `PeHistoryOut` (`core/schemas.py`). Cache-only: no FMP call, no write, no DB
schema change. `status` ("ok" | "etf" | "unsupported_exchange" | "no_profile") gates the chart; under "ok", `stock_status`
("ok" | "adr" | "no_eps" | "no_prices") says why the ticker line is missing while the overlays may still be there.
`points` = `{date, stock, sector, industry}` per trading day (null = gap), `latest_*` = the last value of each series
with its date, `stock_starts` = the first stock point, `industry_fallback`, `sector_available`, `industry_available`.

**Ticker line.** Daily close (cached daily bars through the last completed session, `read_cached_completed_daily_bars`;
split-adjusted, as the cached statements' EPS is) ÷ TTM EPS = the sum of 4 consecutive quarterly `epsDiluted` from the
cached `income_statement/quarterly` row. A TTM value applies **from the 4th quarter's `filingDate`** (fallback: period end
+ 45 days), so no day uses an EPS that was not yet public. A day with TTM EPS <= 0 is dropped (the header P/E's
positive-EPS rule). A window is **broken** (no value from its filing date until the next valid window; an older value is
never carried over it) when neighbouring quarters are not 60-135 days apart (a missing quarter, or a semiannual reporter)
or when a Q4 row's `epsDiluted` equals its fiscal year's annual EPS
(`helpers/ttm.py::is_quarter_content_duplicate_of_annual`, applied to every Q4 in the window; the Defect-B *correction* is
not applied, the window is just dropped). ADR (income-statement `reportedCurrency` ≠ profile `currency`): **no stock line**
and a note (price ÷ EPS would need FX); the sector / industry overlays still show.

**Sector / industry lines.** From `SectorIndustryPe` on the ticker's own profile `exchange`, joined to the bar dates as of
the last stored day within 5 calendar days. `pe <= 0` is a gap (the day stays in the join as NaN so the previous day is not
carried across it). No industry series (Asset Management; HSY, STE, VLTO, CCJ, BF-B on their own exchange): `industry_fallback`,
the UI shows the sector line with a small note and "Industry n/a" in the headline. ETF/fund → `status` "etf"; OTC/CBOE/other →
"unsupported_exchange"; no cached profile → "no_profile": no series, a note, no toggles. Without cached bars the calendar is
the stored sector / industry dates (`stock_status` "no_prices"). No long-history read, so an untracked ticker with no cached
daily bars has no stock line.

**UI.** `PeHistoryCard` (fetch) → `PeHistoryPanel` (headline, two `Switch`es "Overlay sector PE" / "Overlay industry PE", notes) →
`PeHistoryChart` (a sibling of `PriceTargetTrendChart`: recharts lines, one shared hidden P/E axis, `ChartLegend`; stock
`series-1`, sector `series-2`, industry `series-3`). Overlays start off, except when there is no stock line (then they start
on so the chart is not blank). Headline "Stock 28.4 · Sector 22.1 · Industry 24.7" for the latest day, "n/a" for a missing value.
Legend / tooltip labels for the overlays read "<name>: average PE of listed companies (FMP)". The gap is never called a premium
or a discount; the card says the bases differ and the stock P/E can differ from the header P/E (`netIncomePerShareTTM`, live
price). A dashed "Stock P/E starts →" marker shows when `stock_starts` is later than the first point. **Y-range rule**
(`lib/peHistory.ts::peYRange`): 0 to a nice ceiling of 1.15 × the 95th percentile of the visible values (never above the
largest value); points above it are clipped by the axis, the tooltip keeps the true value, and a line says "N days above X
not shown".

**Measured on the real cache (2026-10-09, 584 stock profiles on NASDAQ/NYSE/AMEX; 32 ETFs; 4 OTC/CBOE):** stock line OK 537,
no usable EPS 33, ADR 12, no cached bars 2. 23 tickers' stock line starts after the window start (a new TTM window filed
inside the year, e.g. BA, DLTR, INTC). Quarterly statements are cached with `limit=12` (`TOTAL_QUARTERS_NEEDED`), which covers
the 1-year window for 576 of 585 tickers; a 5-year ticker line would not fit it. Windows dropped, not covered: semiannual
reporters CCEP and FER (182-day gaps), a missing quarter at FLY and Q, and FERG's Q4 2026-06-30 row (duplicate of the annual EPS).
