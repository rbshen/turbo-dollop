# FMP migration Phase 2 — daily prices → FMP (US tickers only): plan (2026-09-24)

Follows `docs/fmp_migration_and_toggles_investigation_2026-09-24.md` (Phase 0). All live FMP
calls were small and made from a scratch folder; DB access was read-only. Nothing was changed
while producing this plan.

## a) Endpoint

**`/historical-price-eod/full`.** Not exactly "split-only" like Massive `adjusted=true`.

| Check | Result |
|---|---|
| NVDA around the 2024-06-10 10:1 split | `full` smooth (120.89 -> 121.79). `non-split-adjusted` shows the raw 1208.9 -> 121.79 cliff. Current cache matches `full` to the cent. |
| High-dividend tickers (VZ, MO, O) | `full` matches the cache (0.0-0.13% max diff). `dividend-adjusted` is off 30-47%: wrong endpoint. |
| Volume | 99.9% of days within 5% of the cache. |
| Rows per call | 5,000 max (~20y). Default with no `from` is 5y. |

**`full` also back-adjusts history for spin-offs.** Full 5-year parity of all 597 US symbols
(585 profiled US-listed, 11 sector ETFs, `^GSPC`) vs the cache: 98.15% of all days within 0.1%.
~30 tickers differ by a constant step that ends at a spin-off date (Massive does not adjust
for spin-offs, FMP does): T +32.5% before 2022-04-11, EXC +40% (2022-02), FDX +24% (2026-06-01),
WDC +32% (2025-02-24), DHR +13% (2023-10), O +3.3% (2021-11-15), plus BDX, J, LEN, ILMN, ZBH,
APTV, FLEX, SPGI, CMCSA, HON. FMP's basis removes artificial cliffs but is not the split-only
basis originally specified; no splits-only FMP endpoint exists.

## b) Data group

`daily_prices` (seeded Premium, unverified, not live). Map `/historical-price-eod/full` and the
`historical_price_eod` cache key to it; mark live; canary probe AAPL `full` `limit=1`; update
"feeds". Side effect: the header avg-volume / dollar-volume tiles (`ticker_summary.py`, nightly
`daily` rows) share the endpoint/key and follow the group (off -> cached row, `/refresh` 503).
Tier cannot be verified live (our key answers 200 to everything); keep Premium, verified tick
unset.

## c) Fallback chain

FMP -> Massive -> Yahoo, per ticker, inside the `DailyBarSource` layer (new `FMPDailySource`
ahead of `MassiveWithYahooFallback`). Empty 200 from FMP is not an error (delisted): falls
through without touching the group's failure counter. 429/5xx/transport errors use the existing
`record_group_failure` (Failing chip after 3). Fallback counts reuse the `fallback_tickers`
out-parameter, meaning "not served by FMP", with the heartbeat message split Massive N / Yahoo M.
Non-US tickers stay on Yahoo.

## d) Nightly incremental

Overlap check instead of a splits-calendar: per ticker `full?from=<last cached bar - 7d>`,
overwrite the last cached bar (fixes provisional 15:50 ET bars), and if any earlier overlapping
close is off by more than 0.5% (split / spin-off / symbol reuse) do a full 5-year refetch for
that ticker. Weekly full resync on Sundays closes the sub-0.5% spin-off gap. ~597 calls/night,
2 KB each; measured 2,500 req/min, 0 429s (~20 s; ~2 min at Starter 300/min, so pace by the
plan). Only the 3:10 trend job fetches; LZ/Breadth/Heatmap/Momentum read the warm shared cache;
no cron changes. `delisted_at` skip is unchanged (filters before `get_or_fetch_bars_batch`).

## e) Full re-backfill

5 years (same tier as today; widest consumer LZ 4y; retention 6y; 10y is P3). ~597 calls x
~274 KB = ~160 MB; ~727k rows written. Replace, not merge: per ticker, one transaction, delete
that ticker's `1d` rows then insert the FMP frame, only if FMP returns a non-empty frame
covering the cached start; otherwise keep old rows and count a fallback. Script
`pipeline/backfills/backfill_fmp_daily_bars.py` with `--dry-run`. Backup first, only with
>= 2 GB free (disk was 78% used, 5.2 GB free, DB 1.28 GB, nightly gz 147 MB).

## f) Symbol-reuse stitching

FMP series for B, BNY, CNSWF, COHR, META are continuous (max 1-day moves <= 30%, real earnings
days). PARA: FMP's PARA is Banzai International (matches the cached profile); the
Paramount->Banzai stitch disappears. AVB: not fixed (FMP has the same 2026-08-17 -64% cliff);
report only. New find: SPCX (cache 1,135 bars stitched vs FMP 71 bars since the 2026-06-12
SpaceX IPO). Re-backfill also lengthens COR, ECHO, FISV, SEZL, EA.

## g) Parity plan

Full 5y closes/volume for all 597 US symbols old vs new (cheap, no sampling), then in-memory
Weinstein + LZ for all US tickers old vs new (no DB writes). Pass: >= 99% of days within 0.1%;
every non-last-day diff > 1% and every stage/zone change traceable to spin-off basis, stitched
symbol, or extra history.

## h) Recompute after the switch (cache-only, in order)

1. `nightly_trend_calculation` (full universe + SPY). 2. `nightly_liquidity_zone_calculation`
(W1-W5 by design). 3. `recompute_ticker_scores` (copies `weinstein_*` to `TickerScore`).
4. Sector Heatmap latest date (+ affected stored rows since 2026-09-18). 5. Breadth: backfill
`--rebuild` for `is_backfilled` rows. 6. Momentum: current month only.

## i) Risks / corrections to the original prompt

Spin-off adjustment (above); disk 78% not ~94%; provisional bars fixed by the overlap check;
Massive/Yahoo remain as rollback; `historical_price_eod` leaves `fundamentals` (header tiles
follow); exchange rule from the cached profile `exchange` (NYSE 379, NASDAQ 199, AMEX 3 incl.
Arca ETFs, CBOE 1 = US; HKSE 6 = non-US; OTC 3); sector ETFs and `^GSPC` have no profile ->
"no profile and no dot" = US; 54 US-listed tickers have foreign domicile and stay US; the 6
HKSE tickers stay non-US.

## Decisions (user, 2026-09-24)

1. Toggle off during P2-P5 = skip FMP and fall through to Massive -> Yahoo (not strict
   cache-only). Status chip wording for this group: "Off — using fallback". Update CLAUDE.md.
2. Overlap check 0.5% + weekly full 5-year resync on Sunday.
3. Accept FMP's spin-off-adjusted basis; document in CLAUDE.md that pre-spin-off prices differ
   from split-only sources (e.g. TradingView) for ~30 tickers.
4. OTC (CNSWF, EVVTY, SINGY) = US, routed to FMP, fallback kept.
5. Header price fallback deferred (Massive snapshot first). Chart D_6M/1Y/2Y move to FMP now.
Also: header avg-volume/dollar-volume tiles follow `daily_prices`; keep Premium label with
verified tick unset; "no profile + no dot" = US; add `--rebuild` to the Breadth backfill.
