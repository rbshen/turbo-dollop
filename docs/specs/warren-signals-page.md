# Warren Signals page: the watch table (phase 1) and the Technical Ideas page (phase 2)

A persistent per-ticker **watch table** built from the Warren arrows on 2h candles. It is not an "in trade now" snapshot:
a row is created or updated when an arrow fires and stays until the user removes it. Phase 1 is the engine, the tables, the
final step of the Warren nightly job and a one-off seed. Phase 2 (2026-10-16) adds the read and remove API, the
**Technical Ideas** page at `/technical-ideas` and the Investing nav menu; see "Phase 2" below.
Arrows are the existing replay's (`docs/specs/warren-signal.md`, the ThinkScripts in `~/warren-thinkscripts/` are the source
of truth for them); this feature only reads them.

## What is built

| Piece | Where |
| --- | --- |
| Update rules (pure) | `backend/analysis/warren_signal/watch.py` (`advance`, `WatchState`) |
| Orchestration, 2nd LP lookup, removal | `backend/data/warren_watch_data.py` |
| Tables | `WarrenWatchRow`, `WarrenWatchCursor` (`backend/core/models.py`; classified KEEP in `data/ticker_data_registry.py`) |
| Nightly step | `update_watch_table` in `pipeline/nightly_warren_signal_calculation.py`, the last thing `main()` does |
| Seed | `uv run python -m pipeline.seed_warren_watch` (the same step on its own, idempotent) |
| Tests | `analysis/warren_signal/test_watch.py`, `analysis/warren_signal/test_thinkscript_parity.py`, `tests/test_warren_watch_data.py` |

### Universe, candles and arrows

The same monitored-ticker union the Warren job reads (`data/watchlists.py::list_monitored_tickers`, lists `E<n>` and `ETF`,
delisted-flagged tickers removed). Per ticker the step rebuilds the Chart tab's 2H·90D series exactly: the fast 2h builder,
`drop_forming_candles`, window-start index (naive America/New_York 09:30 / 11:30 / 13:30 / 15:30), the profile from
`profile_for` and, for SPY/QQQ/TQQQ/TECL, the volume guard (`signal_candles`), then `replay`. A test builds the chart's path
step for step and asserts identical candles and arrows. `as_of` is the last completed candle.

**Time convention.** Every candle time in the table is a window START, as the chart draws it. `WarrenSignalEvent.fired_at`
stamps a window by its LAST 60m bar (10:30 / 12:30 / 14:30 / 15:30), so the two differ by an hour except for the 15:30 candle.

### Row fields (`WarrenWatchRow`, one row per ticker)

`ticker`, `profile` (any / spy / qqq / tqqq / tecl), `latest_arrow_kind` + `latest_arrow_at` (the latest arrow applied to the
row, either direction), `instruction_type` + `instruction_text` (ToS number 1, 2, 3, 10, 20, 30 and the profile's string from
`instructions.py`), `entry_kind` (blue / yellow / null), `entry_at`, `entry_price` (close of the entry arrow's candle),
`stop_price`, `stop_basis` (`10%` / `LP` / `entry` / `none`), `status` (`active` / `breached`), `breached_at`, `last_signal_at`
(the latest UP arrow's candle, type 4 and Gray included), `last_updated_at` (wall-clock server time, moves only when the row's
content changes), `removed_at` (naive America/New_York, so it compares with candle times), `as_of`.

## Update rules

Arrows are applied oldest to newest, candle by candle. On each candle the stop in force **before** that candle's arrows is
tested first, so a stop set on candle t is first tested on t+1 (the ThinkScript's `rawStopHit` needs `barsSinceYellow > 0`).

1. **Breach.** Active row with a stop and `low <= stop` -> `status = breached`, `breached_at` = the candle; stop and last
   instruction are kept. A row with no stop cannot breach.
2. **Up arrows** (one per candle: Blue, then Yellow, then Gray; a Blue on the same candle as a Yellow wins, as the ThinkScript
   resets its yellow count on a Blue):
   - **Blue Up** (type 2): entry blue, entry = this candle, **no stop** (`none`), active. Clears a breach.
   - **Yellow Up** (type 3), no row / breached row / row with no entry: a **fresh entry**: entry yellow, stop = `0.9 x` the arrow
     candle's low, basis `10%`.
   - **Yellow Up** on an active row with an entry: stop = `min(2nd LP, 0.9 x low)`, basis whichever is lower (`10%` on a tie or when
     there is no 2nd LP). The entry is not moved.
   - **First yellow after a Blue** (type 4, from the engine's `first_yellow_after_blue_at`) and **Gray Up** (type 1) on an active row
     with an entry: no action; the instruction and stop stay, `latest_arrow_*` and `last_signal_at` move.
   - A Gray Up with no row creates one with no entry, no stop, type 1.
3. **Down arrows** (one per candle: Yellow Down, then Blue Down, then Gray Down, the ThinkScript's text order) apply only to an
   existing row. The instruction and `latest_arrow_*` always update; `last_signal_at` does not. The stop moves only on an active
   row with an entry: Blue Down -> 2nd LP (basis `LP`); Yellow Down -> 2nd LP if the entry is yellow, else unchanged; Gray Down ->
   `entry_price` (basis `entry`) if the entry is yellow, else unchanged. A down arrow with no row is ignored. If a candle has both
   an up and a down arrow, the up applies first, then the down.
4. **No tighten-only rule.** Stops follow the instruction literally and may move down (a second Yellow whose `0.9 x low` is below the
   first stop lowers it; a Gray Down's entry price can sit above the market).

**2nd LP** = the second-nearest support below the **close of the arrow candle**, from `compute_liquidity_zones_2h` (the Chart tab's
2h LP read) over the candles up to and including that candle, with the **shared LP settings as they are** (`LiquidityZoneSettings`;
`breach_recency_bars` is the 2h override, irrelevant for supports). It is asked for only where a rule needs it: a Yellow Up on an
active row, a Blue Down, a Yellow Down on a yellow entry. No LP is computed for a fresh entry, a Blue Up, a Gray Down or a
no-action arrow. **Dependency:** the engine returns at most `max_lps_per_side` supports (3 today), so the 2nd LP exists only if that
setting is 2 or more; with fewer than two supports (or a setting of 1) the 2nd LP is "none" and the rules fall back as above (a
Yellow keeps the `10%` stop; a down arrow leaves the stop). A settings edit changes later stops, never stored ones.

## Seed, cursor and idempotence

`WarrenWatchCursor` (`ticker`, `processed_through`, `updated_at`) records the last candle already folded in, for every processed
ticker (with a row or not). A ticker with **no cursor is seeded**: it reads the candles after `as_of - 3 months`
(`SEED_MONTHS`); a ticker with a cursor reads only the candles after it. So seed and nightly are the same code. A ticker gets a row
only if an up arrow falls in what it reads: a down arrow with no earlier up arrow in the window creates nothing; a young ticker is
seeded from whatever history it has. The row and the cursor are written in one transaction. A rerun for the same session reads no
candle, makes no LP call and writes nothing but an unchanged `as_of` (test-pinned: the table is identical, `last_updated_at`
included). A catch-up after missed nights reads every candle since the cursor, so a breach on a skipped night is still found.
A ticker that leaves the monitored lists is no longer processed; its row stays as it was.

## Removal

`remove_watch_row(ticker)` sets `removed_at` (naive America/New_York wall clock); the row stays (a soft delete; `DELETE
/api/technical-ideas/warren/{ticker}` calls it, phase 2).
From then on the ticker's candles at or before `removed_at` are not read (an arrow on a candle that started at or before the
removal is ignored even if it completes later), a removed row is not breached or refreshed, and only an up arrow on a later
candle wakes it: it becomes a fresh row (the old state is not carried over, `removed_at` cleared). `list_watch_rows` hides
removed rows by default.

## Nightly step

Final step of `pipeline.nightly_warren_signal_calculation` (1:25 AM), after the Warren replay, sweep and prune, reusing the bars
the job already read. No new cron entry: the `JOB_METADATA` description of the Warren job now says so, and a separate job was not
needed because the step needs the same 60m cache read and must see the same session. Failures are counted on their own
(`watch_failed`), never change the Warren results, and appear in the heartbeat message
(`...; watch table: N created, M changed, F failed`); `check_failure_threshold` applies to the watch step on its own counts.
The LP settings are read once per run.

## Registry

Both tables are `KEEP` in `data/ticker_data_registry.py`: the wipe never deletes them. The cursor is kept with its row on purpose
(a wiped cursor would re-seed and re-apply arrows already folded into the row).

## First seed (2026-10-16, real database)

`pipeline.seed_warren_watch` over the 133 monitored tickers (as_of 2026-10-15 15:30): **114 rows created**, 19 tickers with a cursor and
no row (no up arrow in the window: ACN, ADI, AMD, ANET, CLH, CRM, CTAS, DELL, GWW, HUT, ICE, ILMN, JPM, MEDP, MSFT, SNOW, SPY, TMO, V).
96 active, 18 breached. By latest instruction: type 3 x68 (4 breached), type 10 x17 (8 breached), type 30 x16 (2 breached), type 20 x11
(4 breached), type 2 x1, type 1 x1. Entry kind: yellow 108, blue 4, none 2 (Gray-born: IDXX, MTD). Stop basis: `10%` 64, `LP` 28, `entry` 18,
`none` 4 (DASH and SYK, blue entries with no later stop; IDXX and MTD, no entry). Profiles: QQQ, TECL and TQQQ one row each, SPY none.
The step took 9.6 s (175 LP calls, about 22 ms each); the first run also topped up the 60m cache for the three young tickers (AIPO,
CRWV, SNDK: 21 FMP calls, which the nightly cache read repeats while their history is shorter than 730 days). A rerun was byte-identical
(row and cursor tables hashed before and after) and took 2.0 s for the step with 0 LP calls. A normal night with new candles is
about 133 x (15 ms candles + 24 ms replay) = 5 s plus the few LP calls the night's arrows need.

## Odd results of the literal rules (seen in the seed)

- **Stops above the entry price.** 18 rows have `stop_price > entry_price` (for example ABNB: entry 142.42, Blue Down stop 162.55 LP). That is
  the rule working (the 2nd LP below the arrow candle's close, after a rally), not a bug, but a page reading "stop vs entry" must expect it.
  A Gray Down also sets the stop to the entry price, which can sit above the market (it breaches on the next candle).
- **Stops can move down.** A second Yellow's `0.9 x low` can be below the first Yellow's stop; there is no tighten-only rule.
- **A Blue entry gets its first stop from a later down arrow.** PAYX: blue entry 101.80, Blue Down moved the stop to an LP at 101.42.
  Blue entries otherwise carry no stop and cannot breach.
- **Gray-born rows** (IDXX, MTD) have no entry and no stop; their down arrows change only the text. IDXX's yellow trade pre-dates the 3-month
  window, so the table shows only its Gray Up.
- **Young tickers** are seeded from the history they have; a 180-day-old Gray/Yellow label can still be wrong at the left edge of their
  replay (`docs/specs/warren-signal.md`, warm-up).
- **TQQQ:** the 692,200 volume cap quirk (profile data, `warren-signal.md`) means its Blue branches SOS1 can essentially never fire; it
  is untouched here. TQQQ and QQQ each have a Yellow Up fresh entry on 2026-10-15 13:30.
- **No Blue Up has fired for any ticker in the window except four rows** (BKNG, DASH, PAYX, SYK), so the Blue paths have little live data.

## Phase 1 limits (still true)

- The table does not protect a ticker in the tracked-universe sense (KEEP, not PROTECTING): a ticker that falls out of every
  list keeps its stale row, and the user decides when to remove it.
- A watch row is end-of-day state (nightly); there is no intraday refresh.
- A down arrow on a breached row only updates the text; a gray-only row (no entry, no stop) is listed like any other.

## Phase 2: API, page, nav

### API (`core/main.py`, schemas `WarrenWatchOut` / `WarrenWatchRowOut`, data `data/warren_watch_data.py::watch_table`)

| Route | Role | What |
| --- | --- | --- |
| `GET /api/technical-ideas/warren` | viewer | Every non-removed `WarrenWatchRow` plus `as_of`. Reads the stored tables only: no FMP call, no write, no `TickerView` touch (`tests/test_viewer_rules.py` runs it with the other viewer GETs). |
| `DELETE /api/technical-ideas/warren/{ticker}` | admin | `remove_watch_row`: sets `removed_at`. 404 when the ticker has no row or it is already removed; 422 for a malformed symbol (it carries `TickerPath`, as the registry test requires). |

Both are registered in `core/route_roles.py`. The route lives under `technical-ideas`, not `tickers/{ticker}`, because it is a
page-level table, not a ticker resource (a viewer is not restricted to tracked tickers here: the table is already the monitored set).

**`as_of`** is the newest `WarrenWatchCursor.processed_through` (the last completed 2h candle any ticker was folded through; it
covers tickers with no row), falling back to the rows' own `as_of`; `null` only before the first seed.

**Row fields:** `ticker`, `profile`, `latest_arrow_color` (`blue`/`yellow`/`gray`) and `latest_arrow_direction` (`up`/`down`) split from the
stored kind, `latest_arrow_at`, `instruction_type`, `instruction_text`, `entry_kind`, `entry_price`, `stop_price`, `stop_basis`, `status`,
`breached_at`, `last_signal_at`, `last_updated_at`, `age_bars`, `last_signal_age_bars`. `entry_at` and `removed_at` are not returned.

**Time convention.** Every datetime in the response is a naive America/New_York ISO string. Candle times are window STARTS, as the chart draws
them. `last_updated_at` is stored as naive server-local wall clock (UTC on the box) and converted to ET in the response.

**Ages.** `age_bars` = completed 2h candles after the latest arrow's candle up to the table's `as_of` (0 = the arrow is on the last candle);
`last_signal_age_bars` is the same for the latest UP arrow (`last_signal_at`, the date the page shows). They are counted on the NYSE
calendar (`helpers/trading_calendar.py::xnys_sessions`, imported lazily): 4 windows a session (09:30, 11:30, 13:30, 15:30), 2 on an early close
(13:00), none on a holiday. This is a calendar count, not a bars read, which keeps the endpoint cache-only; it equals the candle count
in the series because the series has one candle per window that has bars. `last_signal_age_bars` is an addition to the brief (which asked
for one age): the page's Last signal column shows `last_signal_at`, and its age must be measured from that candle, not from a later down arrow.

### Page (`/technical-ideas`, title "Technical Ideas")

`app/technical-ideas/page.tsx` lists sections; each strategy is a self-contained section component built on
`components/technical-ideas/TechnicalIdeaSection.tsx` (heading, short timeframe tag, "As of" stamp, body, footnote). The first is
`WarrenWatchSection`: heading **RSI WVF ADX by Warren**, tag **2h**, header stamp "As of Oct 15, 15:30 ET" (the table's `as_of`, a candle START).
Another strategy adds its own section component, hook and table; nothing here changes. Data: `lib/hooks/useWarrenWatch.ts` (SWR, no polling).

Table (`WarrenWatchTable`, modelled on `MomentumTable`: kit Table, compact Badge pills, mono tabular numbers, whole-row click opens
`/tickers/{t}` in a new tab; the ticker link and the Remove control keep their own click):

| Column | Content |
| --- | --- |
| Ticker | Link; a profiled ticker (spy/qqq/tqqq/tecl) shows "<profile> profile" beneath. |
| Signal | Up/down pill in the arrow's colour: Blue = `chart-ema21` (the chart's own blue for Blue arrows), Yellow = `chart-warren-yellow`, Gray = `chart-warren-gray`. Title: the arrow candle's time. |
| Instruction | The stored text (wraps; full text in the title). |
| Stop | Price plus a neutral basis tag (`10%`, `LP`, `Entry`); a dash when there is no stop. A stop above the entry price shows normally with a small info icon whose tooltip says the latest instruction set it (2nd LP / entry price), so it does not read as a bug. |
| Status | Green "Active", or a red **Stop breached** badge (title: the breaching candle). |
| Last signal | `last_signal_at` (ET) and its age in bars ("this candle", "1 bar ago", "5 bars ago"). |
| Last updated | `last_updated_at` (ET), when the row's content last changed. |
| (actions) | Admin only: trash icon, then an inline Remove? / Confirm / Cancel (the Watchlist delete pattern). A viewer sees no control (`<AdminOnly>`). |

Default and only sort: `last_signal_at` descending, ties by ticker (`lib/technicalIdeas.ts::sortByLastSignal`). States: skeleton rows while
loading, an error line, and "No tickers on the watch table yet" when empty.

Removal is a soft remove: the row disappears from the page and a nightly rerun does not bring it back; only an up arrow on a candle after the
removal does (Removal section above; `tests/test_warren_watch_api.py`).

### Nav

Top-level links are Stocks, ETFs, Watchlist, Momentum; then two dropdowns (the Markets pattern, one `NavMenu` component):
**Investing** (Opportunities, Technical Ideas) and **Markets** (Sectors, Breadth). Opportunities left the top level; its page and URL
are unchanged. `/technical-ideas` is a same-tab page like `/opportunities`. Investing is marked current on either route.

### Open for a later phase

- **Intraday refresh.** The table is as of the last nightly run; a refresh during the session would need the 60m cache topped up and the step
  run outside the Warren job (the cursor makes that safe), plus a decision on whether a forming candle may ever breach a stop.
- **A second strategy section** needs only a new section component and hook; the page and the shell do not change.
- **Sorting and filtering** (by status, signal colour, age) are not built; the default order is the only one.
- **Stale rows.** A ticker that left every monitored list keeps its row and its frozen `as_of`; the page does not flag it.
