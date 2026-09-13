# AAPL Technical Tab Bug Investigation — 2026-09-13

Investigation only, no code changes. Both bugs reported against AAPL's Technical tab
("Trend started" showing a bare "—", and an empty "Past cycles this trend" timeline) trace
to a **single root cause: a stale, not-yet-recomputed `TrendAnalysis` row** — not a frontend
fallback bug, not a `state_machine.py` logic bug, and not "genuinely zero cycles." This is
the exact `_add_missing_columns`-has-no-backfill transient window CLAUDE.md documents for
every other nullable Phase field on this table (`ad_bullish_divergence`, `sma20_cross`,
etc.) — now actually observed in the wild for the first time, because the nightly cron
hadn't run yet against the new code when this was reviewed.

## 1. AAPL's actual cached row, as stored

Pulled directly from `backend/fathom.db` (`TrendAnalysis` table), not inferred from the UI:

| Field | Stored value |
|---|---|
| `computed_at` | `2026-09-13 03:10:51.786388` |
| `trend_state` | `"uptrend"` |
| `persistence_count` | `8` |
| `bars_since_confirmation` | `21` |
| `last_confirmed_swing_json` | `{"date": "2026-08-12", ...classification: "HL"}` |
| `warning_flag` | `True` |
| `warning_swing_json` | `{"date": "2026-08-19", ...classification: "LH"}` |
| `pullback_occurred_since_flip` | `True` |
| **`trend_started_json`** | **`None`** |
| **`trend_started_is_lower_bound`** | **`None`** |
| **`pullback_history_json`** | **`None`** |
| `ad_bullish_divergence` | `True` |
| `weinstein_stage` | `"advance"` |

Every Phase-1/2 field (`trend_started_json`, `trend_started_is_lower_bound`,
`pullback_history_json`) is `None` — exactly the shape a row computed before those columns
existed reads as, per `core/models.py::TrendAnalysis`'s own documented convention (a raw
`ALTER TABLE` with no backfill; existing rows read `NULL` until the next nightly run
rewrites every field).

## 2. Stale row vs. genuine bug — confirmed stale, by direct comparison

**Timing.** AAPL's `computed_at` (`03:10:51`) is the 3:10 AM nightly cron's run on
2026-09-13. The Phase 1 commit (`f484985`, adding `trend_started`/`flip_swing`) landed at
`07:55:17` that same day; Phase 2 (`e17d04e`, adding `pullback_history`) at `08:09:28` — both
**over 4.5 hours after** the nightly run that wrote this row. The row is old code's output,
not new code's output with a bug in it.

**Confirmed by forcing a real recompute**, not just by timestamp arithmetic — ran
`compute_and_store_trend_analysis("AAPL")` (the exact same production function the nightly
cron calls, against the exact same cached Yahoo price history, 1256 bars, no fixture/mock
involved):

| Field | Stale row (03:10 run) | Fresh recompute (today, current code) |
|---|---|---|
| `trend_state` | uptrend | uptrend (unchanged) |
| `persistence_count` | 8 | 8 (unchanged) |
| `warning_flag` / `warning_swing` | True / Aug 19 LH | True / Aug 19 LH (byte-identical) |
| `trend_started` | *(field didn't exist)* | **2026-06-02, HH, is_lower_bound=False** |
| `pullback_history` | *(field didn't exist)* | **2 cycles**: Jun 16→Jun 25, Aug 7→Aug 12 |

`trend_state`/`persistence_count`/`warning_flag`/`warning_swing` are byte-identical between
the stale row and the fresh recompute — proving the classification/state-machine logic
itself is deterministic and unaffected; only the two genuinely-new fields differ, and they
differ because the stale row never had a chance to compute them at all, not because they
computed wrong. This directly rules out both alternative explanations in the task: no gap
in `NearTermCard.tsx`'s lower-bound fallback (it's never reached, since `trend_started`
itself is `null`, not a populated-but-zero object), and no `state_machine.py` edge case
specific to AAPL's swing sequence.

## 3. Scope: 572 of 573 tracked tickers (99.8%) are in the same stale state

```
total rows:                              573
stale (trend_started_json IS NULL):      572
stale (pullback_history_json IS NULL):   572
stale on BOTH fields:                    572
fresh (trend_started_json NOT NULL):       1   <- CTAS only
```

**The one fresh row, CTAS, is not evidence of partial rollout or a working nightly
backfill** — it's an artifact of this same investigation thread manually calling
`compute_and_store_trend_analysis("CTAS")` twice during Phase 1/2's own verification
(`computed_at` for CTAS is `08:04:02`, after both feature commits). Excluding CTAS, the
**latest** `computed_at` across all other 572 tickers is `2026-09-13 03:11:30` — i.e.
literally every other tracked ticker was last written by the same pre-Phase-1 nightly run,
none later. This is universe-wide, not AAPL-specific.

Three tickers (SOFI, SNAP, ROKU) carry an even older `computed_at` (2026-08-21, 2026-09-06
×2) — a separate, smaller reliability question (their most recent nightly attempts likely
failed, per `compute_and_store_from_rows`' per-ticker try/except and the "stale is better
than nothing" fallback in `get_trend_analysis_data`), worth checking
`logs/nightly_trend_calculation.log` for if they're still stale after tonight's run, but
unrelated to the Phase 1/2 rollout question itself.

**Will the nightly cron naturally backfill these — no one-time script needed?** Yes, confirmed
by reading `pipeline/nightly_trend_calculation.py` directly: it calls
`compute_and_store_from_rows(ticker, ...)` **unconditionally for every ticker in the full
tracked universe on every run**, regardless of whether that ticker's underlying Yahoo price
cache was itself stale enough to need a fresh fetch — `_upsert` always writes every field,
including `trend_started_json`/`pullback_history_json`, from scratch each time. The live
crontab's `nightly_trend_calculation` entry (`10 3 * * *`) is confirmed byte-identical to
`backend/crontab.txt` (no drift, unlike the historical incident CLAUDE.md documents for a
different job) — so **the very next scheduled run (tonight, ~3:10 AM) will repopulate all
572 rows**, AAPL included, with no manual intervention required. (Separately, while checking
this: two *unrelated* jobs — `nightly_warren_signal_calculation` and `backup_db`'s current
3:55 AM slot — are missing/stale in the live crontab vs. `crontab.txt`, the same class of
drift CLAUDE.md's "Cron job heartbeat" section warns about; flagged here since it was
noticed during this check, but it doesn't affect `nightly_trend_calculation`, which is
correctly installed.)

Today's on-demand path (`GET /api/tickers/AAPL/trend-analysis`) won't self-heal this before
then either: `Settings.yahoo_price_cache_staleness_days = 1`, and AAPL's row is only ~5-25
hours old depending on when it's viewed today, so `get_trend_analysis_data`'s own
`is_stale` check reads `False` and serves the cached (pre-Phase-1) row as-is rather than
triggering a fresh compute.

## 4. Not a genuine bug — both frontend and backend traced clean

- **`NearTermCard.tsx`**: `trendStarted ? fmtSwingDate(trendStarted.date) : "—"` is exactly
  correct for `trend_started: null` — the bare "—" is the documented "no data at all" case,
  distinct from (and never confused with) the lower-bound case, which only ever renders once
  `trend_started` is a real, non-null object. There is no missing branch here; the fallback
  simply hasn't been exercised for AAPL yet because the upstream field is null, not because
  a real lower-bound value failed to render.
- **`state_machine.py`**: the fresh recompute reproduces AAPL's exact `trend_state`/
  `persistence_count`/`warning_flag`/`warning_swing` and additionally produces a fully
  sane, real `trend_started` (a genuine mid-history flip, not even a lower-bound edge case)
  and 2 genuine `pullback_history` cycles. Nothing about AAPL's specific swing sequence
  breaks either mechanism.

## 5. Part 2's empty timeline: same root cause, NOT genuinely zero cycles

Directly answered by the same recompute, not assumed: AAPL's current uptrend (started
2026-06-02) has **2 real, completed pullback cycles** (Jun 16 → Jun 25, Aug 7 → Aug 12)
before the currently-pending one (warning fired Aug 19, still unresolved — matching the
live "Pullback pending" status exactly). The "Past cycles this trend" section hiding
itself was masking real data, not correctly reporting an empty trend.

Worth noting as a real, if secondary, finding from this investigation: **`pullback_history`
has no way to distinguish "stale row" from "genuinely zero cycles" at the API boundary**,
by original Phase 2 design (`_pullback_history_from_json(None) -> []`, chosen because the
two cases were considered indistinguishable and equally "nothing to show"). That
reasoning holds for a mature, long-settled feature, but it's exactly why this specific
bug report couldn't be resolved by inspecting `pullback_history` in isolation — it took
cross-referencing the sibling `trend_started_json IS NULL` (which *is* distinguishable
from a real lower-bound value) to establish staleness, then a forced recompute to confirm
it wasn't a coincidental real zero. A future reader hitting this same ambiguity on a
ticker where `trend_started` is *also* null-vs-populated-ambiguous (impossible today,
since `trend_started` and `pullback_history` are always written together in the same
`_upsert` call — but worth knowing this cross-check trick won't always be available if the
two ever become decoupled) would need to force a recompute directly, as done here.

## Bottom line

One root cause, both symptoms: AAPL's cached row (and 571 others, 99.8% of the tracked
universe) predates the Phase 1/2 deploy by several hours and has never been recomputed
since. No frontend bug, no state-machine bug, no backfill script needed — confirmed the
nightly cron unconditionally recomputes every tracked ticker every night and is correctly
scheduled, so this self-heals universe-wide on the next run (tonight, ~3:10 AM). If the fix
is wanted sooner than that, a manual one-off `uv run python -m
pipeline.nightly_trend_calculation` (full run) or a targeted `--tickers AAPL` run would
backfill on demand — noted as an option, not executed here, since this was scoped as
investigation only.
