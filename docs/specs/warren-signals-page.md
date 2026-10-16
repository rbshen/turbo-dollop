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
`stop_price`, `stop_basis` (`10%` / `LP` / `entry` / `none`), `stop_moved_at` + `stop_moved_by` (the candle that last changed the stop VALUE and the rule that did it; see "Trailing stop and stop age"), `status` (`active` / `breached`), `breached_at`, `last_signal_at`
(the latest UP arrow's candle, type 4 and Gray included), `last_updated_at` (wall-clock server time, moves only when the row's
content changes; since 2026-10-16 a trail move or a stop-age change is a content change too, so a row can now update on a candle with no arrow), `removed_at` (naive America/New_York, so it compares with candle times), `as_of`.

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
   - **A Gray Up on a BREACHED row** (2026-10-16) moves `latest_arrow_*` only, so the pill shows the Gray, but `last_signal_at` stays
     frozen: a "stay out until Blue" arrow is not a signal worth re-dating the row for. A Gray Up on an active row (with or without an
     entry) advances `last_signal_at` as before.
3. **Down arrows** (one per candle: Yellow Down, then Blue Down, then Gray Down, the ThinkScript's text order) apply only to an
   existing row. The instruction and `latest_arrow_*` always update; `last_signal_at` does not. The stop moves only on an active
   row with an entry: Blue Down -> 2nd LP (basis `LP`); Yellow Down -> 2nd LP if the entry is yellow, else unchanged; Gray Down ->
   `entry_price` (basis `entry`) if the entry is yellow **and the entry price is BELOW the Gray Down candle's close**, else unchanged
   (2026-10-16: an entry at or above the close would put the stop above the market and breach on the next candle, so the row keeps its
   stop, basis, status, `breached_at` and entry, and only `latest_arrow_*` and the instruction type/text update; a blue entry or a row
   with no entry is unchanged as before). **The ThinkScript computes no stop for a Gray Down** (its text only says "Adjust stop
   accordingly"); this is a rule on the instruction text only, like the Blue Down 2nd LP. A down arrow with no row is ignored. If a candle has both
   an up and a down arrow, the up applies first, then the down.
4. **No tighten-only rule for ARROWS.** Stops follow the instruction literally and may move down (a second Yellow whose `0.9 x low` is below the
   first stop lowers it; a Gray Down's entry price can sit above the market). Only the trail below is raise-only.
5. **Trailing (2026-10-16).** After a candle's arrows, an ACTIVE row whose stop basis is `LP` takes the 2nd LP as of THAT candle; if it is higher than the
   stop, the stop is raised to it (basis stays `LP`). It never lowers a stop, never trails a `10%`, `entry` or `none` stop, and does not touch a breached row.
   It runs on every 2h candle the row reads, arrow or not. The breach test on a candle uses the stop as it stood BEFORE that candle (rule 1), so a stop trailed on
   candle t is first tested on t+1. Consequence: a trail that is hit on the next candle breaches, and the next Yellow Up then creates a FRESH entry (a
   breached row restarts), so entry prices on trailed rows jump.

### Trailing stop and stop age

`stop_moved_at` (naive ET candle start) and `stop_moved_by` record the last change of the stop VALUE: `yellow_up_entry` (fresh entry), `yellow_up_repeat`,
`blue_down`, `yellow_down`, `gray_down`, `trail`. Re-setting the same value is not a move (a Blue Down whose 2nd LP equals the stop changes the text and the basis
at most, not the stop age); a stop that becomes none (a Blue Up on a row that held one) clears both; a fresh entry always stamps them. Both are nullable
(`_add_missing_columns` adds them on startup); a row not yet rebuilt shows no stop age. They are part of the row's content (`_content`), so a trail changes
`last_updated_at`.

**LP cost.** Trailing asks for the 2nd LP only for an ACTIVE row with an `LP` stop, on every candle it reads (the full `compute_liquidity_zones_2h` slice, never
the pivot-only shortcut, which gives different results). Rows on a `10%`/`entry`/`none` stop and breached rows cost nothing. The lookup caches by candle, so an
arrow candle that also trails asks once. A normal night reads at most 4 new candles per ticker, so about 4 LP calls (~22 ms each) per active LP-stop row.

**2nd LP** = the second-nearest support below the **close of the arrow candle**, from `compute_liquidity_zones_2h` (the Chart tab's
2h LP read) over the candles up to and including that candle, with the **shared LP settings as they are** (`LiquidityZoneSettings`;
`breach_recency_bars` is the 2h override, irrelevant for supports). It is asked for only where a rule needs it: a Yellow Up on an
active row, a Blue Down, a Yellow Down on a yellow entry, and (2026-10-16) every candle of an active LP-stop row for the trail. No LP is computed for a fresh entry, a Blue Up, a Gray Down or a
no-action arrow on a row that does not hold an LP stop. **Dependency:** the engine returns at most `max_lps_per_side` supports (3 today), so the 2nd LP exists only if that
setting is 2 or more; with fewer than two supports (or a setting of 1) the 2nd LP is "none" and the rules fall back as above (a
Yellow keeps the `10%` stop; a down arrow leaves the stop). A settings edit changes later stops, never stored ones.

## Seed, cursor and idempotence

`WarrenWatchCursor` (`ticker`, `processed_through`, `updated_at`) records the last candle already folded in, for every processed
ticker (with a row or not). A ticker with **no cursor is seeded**: it replays the candles after `as_of - 12 months`
(`SEED_MONTHS`, was 3 until 2026-10-16); a ticker with a cursor reads only the candles after it. So seed and nightly are the same code.
**The 12-month replay only determines the state; a first-time ticker gets a row only if an up arrow (Blue, Yellow or Gray) fell in the
LAST 3 months** (`ROW_MONTHS`, candles after `as_of - 3 months`; `_has_recent_up`). A down arrow with no earlier up arrow creates nothing; a
young ticker is seeded from whatever history it has. Why 12 months: a 3-month seed made an arrow near the window start look like a fresh
entry when an earlier trade existed (MAR: its Aug 5 Yellow became the entry at 358.69 where the June yellow implied about 378).
A ticker that already has a cursor but no row (no recent up arrow at seed time) is not re-seeded: a later up arrow creates its row fresh.
**Warm-up.** The watch path replays the WHOLE cached 60m history (`LOOKBACK_DAYS` = 730 days requested) and only cuts what it applies
(`after`), so the engine has everything before the 12-month start as warm-up (about a year for a full-history ticker). The 180-day
`EVENT_WRITE_WARMUP_DAYS` buffer belongs to the stored `WarrenSignalEvent` writes and is not part of this path (unchanged). A ticker whose
first candle is later than start minus 180 days has a thinner warm-up (AIPO today, 283 days of history); the rebuild script lists them. The row and the cursor are written in one transaction. A rerun for the same session reads no
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

(3-month window and the old Gray Down rule; replaced by the 12-month seed and the new rule above, see "Second rebuild" at the end.)
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
  A Gray Down used to set the stop to the entry price even when that sat above the market (it breached on the next candle); since 2026-10-16 it
  does so only when the entry price is below the Gray Down candle's close (rule 3).
- **Stops can move down.** A second Yellow's `0.9 x low` can be below the first Yellow's stop; there is no tighten-only rule.
- **A Blue entry gets its first stop from a later down arrow.** PAYX: blue entry 101.80, Blue Down moved the stop to an LP at 101.42.
  Blue entries otherwise carry no stop and cannot breach.
- **A Gray Up on a breached row** used to advance `last_signal_at` (WDC: the Gray of 2026-10-15 re-dated a row whose trade began 2026-09-16 and was stopped on 10-13). It no longer does (rule 2); the page also shows such a row's instruction as "Stop hit".
- **Gray-born rows** (IDXX, MTD) have no entry and no stop; their down arrows change only the text. The page shows them as "No entry", not "Active". IDXX's yellow trade pre-dates the 3-month
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
`breached_at`, `last_signal_at`, `last_updated_at`, `age_bars`, `last_signal_age_bars`, and (2026-10-16) `entry_at`, `last_price`, `last_price_date`, `pl_pct`, `stop_distance_pct` (next paragraph), `stop_moved_at` (naive ET) and `stop_moved_by` (null on a row with no stop age). `removed_at` is not returned.

**Price fields (2026-10-16).** `last_price` / `last_price_date` are the **latest completed DAILY close** and its date, read per ticker from the cached 1d bars (`clients/shared_bars_cache.py::read_cached_completed_daily_bars`, 30-day lookback; a pure read, so the endpoint stays cache-only and write-free for a viewer: no FMP call, no write, `tests/test_warren_watch_api.py` and `tests/test_viewer_rules.py`). A live in-progress bar is never used. A ticker with no cached daily bar returns nulls for all four computed fields. Both ratios are **fractions** (0.10 = 10%), defined once in `data/warren_watch_data.py`: `pl_pct = (last_price - entry_price) / entry_price` (null with no entry; a BREACHED row uses `stop_price` in place of `last_price`, see the P/L % column) and `stop_distance_pct = (last_price - stop_price) / last_price` (null with no stop; positive = price above the stop, negative = already below it). `entry_price` is the **close of the entry candle**, not a fill. **Intraday refresh:** if an intraday refresh is ever added (see "Open for a later phase"), "Last" should switch to the latest candle close instead of the daily close.

**Time convention.** Every datetime in the response is a naive America/New_York ISO string. Candle times are window STARTS, as the chart draws
them. `last_updated_at` is stored as naive server-local wall clock (UTC on the box) and converted to ET in the response.

**Ages.** `age_bars` = completed 2h candles after the latest arrow's candle up to the table's `as_of` (0 = the arrow is on the last candle);
`last_signal_age_bars` is the same for the latest UP arrow (`last_signal_at`, the date the page shows). They are counted on the NYSE
calendar (`helpers/trading_calendar.py::xnys_sessions`, imported lazily): 4 windows a session (09:30, 11:30, 13:30, 15:30), 2 on an early close
(13:00), none on a holiday. This is a calendar count, not a bars read, which keeps the endpoint cache-only; it equals the candle count
in the series because the series has one candle per window that has bars. `last_signal_age_bars` is an addition to the brief (which asked
for one age) for a column that showed `last_signal_at`. Since 2026-10-16 the Last signal column shows `latest_arrow_at` and reads `age_bars`; `last_signal_age_bars` is still returned (unchanged, not removed) but no longer read by the UI, and `last_signal_at` appears only in that column's tooltip.

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
| Instruction | The stored text, wrapped to at most 2 lines in a 220 to 360 px cell, truncated beyond that, the full text in the tooltip (the longest string is the profiled Yellow Up, about 124 characters; the generic set tops out near 50). **A breached row** shows **"Stop hit"** with "since <breach candle, ET>" beneath instead (display only: the stored instruction type, text and stop are unchanged; the tooltip carries "Last instruction: <stored text>"). |
| Entry | `entry_price`, mono, dash with no entry (Gray-born rows). Tooltip: entry kind (Blue/Yellow), the entry candle's ET stamp (`entry_at`), its age ("7 months ago", `fmtAgeAgo`) and "The close of the entry candle, not an actual fill." |
| Last | `last_price`, the latest daily close; tooltip "Daily close of <last_price_date>"; dash when null. |
| P/L % | `pl_pct`, signed, one decimal (`fmtSignedPct1`). **Active row:** `(last_price - entry_price) / entry_price`, green above the entry, red below. **Breached row (2026-10-16): frozen at the stop**, `(stop_price - entry_price) / entry_price`, computed server-side (`data/warren_watch_data.py::row_pl_pct`) from stored fields, so it does not move with the daily close; an estimate of the exit, not a fill (a gap through the stop is not included). Neutral colour (no green/red) with the tooltip "Stopped out at $<stop> on <breach date> ET. P/L estimated at the stop, not a real fill; gaps through the stop are not included." (`breachedPlTitle`). A new Yellow/Blue Up that returns the row to active switches it back to the active formula by itself. Dash with no entry, or on a breached row with no stop. Last and Stop dist. keep following the cached daily close, so on a breached row Stop dist. is how far price has moved from the stop since the stop-out. |
| Stop | Price plus a neutral basis tag (`10%`, `LP`, `Entry`); a dash when there is no stop. A stop above the entry price shows normally with a small info icon whose tooltip says the latest instruction set it (2nd LP / entry price), so it does not read as a bug. **Stop-age tooltip** on the cell (`stopAgeTitle`): "Set at entry, Jun 11, 09:30 ET (10% of the candle low)", "Repeat yellow, Aug 3, 11:30 ET (lower of 2nd LP and 10%)", "Set Oct 15, 11:30 ET by Blue Down (2nd LP)" / "...by Yellow Down (2nd LP)", "Gray Down: stop set to entry, Sep 23, 13:30 ET", "Trailed to 2nd LP Oct 16, 13:30 ET", each followed by " · <age>" (`fmtAgeAgo`); no line when `stop_moved_at` is null. |
| Stop dist. | `stop_distance_pct`, signed, one decimal. **Red only when negative on an ACTIVE row** (the last close is below a stop the row still holds: a missed breach; tooltip says so); neutral otherwise, including a breached row. Dash with no stop. |
| Status | Green "Active", or a red **Stop breached** badge (title: the breaching candle). A row with **no entry price** (born from a Gray Up) shows a neutral **"No entry"** badge instead of Active, its tooltip saying no up-arrow entry fell inside the 12-month replay window so an earlier trade may exist (`NO_ENTRY_NOTE` in `lib/technicalIdeas.ts`; it said "3-month seed window" until the seed went to 12 months); its Stop cell keeps the dash. |
| Last signal | The candle start (ET) of the **latest arrow of any kind**, the same arrow as the Signal pill (`latest_arrow_at`), with its age in bars from `age_bars` ("this candle", "1 bar ago", "5 bars ago"). The tooltip carries **"Last entry/refresh: <date, ET>"**, the latest UP arrow (`last_signal_at`). |
| Last updated | `last_updated_at` (ET), when the row's content last changed. |
| (actions) | Admin only: trash icon, then an inline Remove? / Confirm / Cancel (the Watchlist delete pattern). A viewer sees no control (`<AdminOnly>`). |

**Fit (2026-10-16).** No horizontal scrolling: the page container is `max-w-7xl px-8`, so the table has at most 1216 px of content at a 1280 px laptop and on a wide monitor alike. Twelve columns fit by cell padding `pr-2.5` (the kit's `pr-4` is overridden on every cell and head), compact mono numbers (`text-xs`, `whitespace-nowrap`), and the Instruction cell as the only wrapping one (`min-w-[160px] max-w-[300px]`, was 220/360; its 2-line clamp and full-text tooltip are unchanged). Estimated natural width about 1.08k px (Ticker 80, Signal 90, Instruction 160 to 300, Entry/Last 65 each, P/L 55, Stop 100, Stop dist. 50, Status 90, Last signal 85, Last updated 85, actions 32, plus 10 px per column); it was reasoned from the classes and tested for tight padding and nowrap, not viewed in a browser (CLAUDE.md).

**Sticky header.** The table sits in its own scroll box (`max-h-[70vh] overflow-auto`, the Watchlist table's pattern) and every header cell is `sticky top-0 z-20 bg-page`, so the header row stays visible while the rows scroll; the top nav is a separate sticky element and the page shell is unchanged.

Default and only sort: `latest_arrow_at` descending (every arrow, up or down, any colour, so the order always agrees with the Signal pill), ties by ticker (`lib/technicalIdeas.ts::sortByLatestArrow`). States: skeleton rows while
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
- **Verify state-change logic on live data.** The transitions (entry, refresh, breach, down-arrow stop updates, reset by a new yellow, removal then new arrow) cannot be fully verified yet; recheck as real arrows fire, starting with a blue entry, which has little live coverage.

## Correcting stored rows after a rule change (2026-10-16)

A rule change does not touch stored rows (the cursor means old arrows are never re-read), so a stored row can disagree with the new rule until it is rebuilt.
`uv run python -m pipeline.backfills.rebuild_warren_watch` (a dry run; `--apply` writes) replays every non-removed row from the ORIGINAL seed start
(2026-07-15 15:30, not a slid 3-month window, so entries and no-entry rows stay as seeded) through the row's own cursor, with the current rules, the cached 60m
bars (no FMP call) and today's LP settings, and compares each result with the stored row field by field. It corrects only a row whose single difference is
`last_signal_at`, and writes only that column: `removed_at`, the cursor, `last_updated_at` and `as_of` are never touched and a removed row is skipped, so nothing
is resurrected. Any other difference is printed and the row left alone for review. Dry run on the real database after the Gray Up rule change: 114 non-removed rows,
113 identical, one correction (WDC `last_signal_at` 2026-10-15 15:30 to 2026-09-16 09:30), none skipped. Applied the same day: only that one cell changed (a hash of every other row column and the cursors was identical before and after), and a rerun reports 114 identical.

## Second rebuild: Gray Down rule and the 12-month seed (2026-10-16)

Two rule changes (Gray Down at or above the entry price leaves the stop alone; first-time tickers replay 12 months, row only with an up arrow in
the last 3) left the stored rows built under the old rules. `pipeline.backfills.rebuild_warren_watch` was rewritten for it (the earlier
`last_signal_at`-only correction is superseded, its result above stands):

- Replays every non-removed row from `REBUILD_START` (2025-10-15 15:30 = the first seed's as_of minus 12 months, a fixed date) through the row's
  own cursor, with the current rules, the cached 60m bars (no FMP call) and today's LP settings, and diffs every field.
- **Dry run by default.** `--apply` writes only the rows that differ (the fields of `WarrenWatchRow` the state covers, instruction text included) and never
  touches `removed_at`, the cursor, `as_of` or `last_updated_at`; removed rows are skipped, a ticker with no row never gets one.
- **Mismatch guard:** a row that already equals the new replay is identical (a rerun after `--apply` reports every row identical); a row that differs is rebuilt only if the same
  bars and LP settings replayed under the OLD rules (3-month window from 2026-07-15 15:30 and the old Gray Down rule, emulated inside the script) reproduce the stored row
  exactly; if not, the difference is not explained by the rule changes, so the row is printed and skipped.
- It also prints a history check (first candle vs the replay start and the 180-day warm-up).

Dry run on the real database (before `--apply`): 114 non-removed rows, 46 identical, 68 changing, 0 skipped by the guard; one ticker with short history (AIPO, 283 days,
unchanged). The 68 are almost all an earlier entry: a yellow trade that never breached keeps its first Yellow as the entry (later Yellows only refresh the stop), so entries
move back months and many entry prices are far below the market. Stop changes 21, breached -> active 4 (CIBR, LLY, MAR, SEZL), active -> breached 2 (IDXX, MTD: now a
yellow trade found, breached months ago).

**Applied 2026-10-16** (owner approval): the 68 rows were written. A before/after dump of both tables showed exactly 68 rows changed, every other row byte-identical, `removed_at`, `as_of`,
`last_updated_at` and all 133 cursors unchanged for every row. A rerun reports 114 identical, 0 changing, 0 skipped (the first version of the guard skipped already-rebuilt rows on a rerun, fixed the
same day). MAR is now yellow 353.09 (2026-05-05), stop 367.04 LP, active; IDXX and MTD have yellow entries and are breached; WDC and CRDO keep their stops and breaches with older entries.

## Third rebuild: trailing stop and stop age (2026-10-16, applied)

`pipeline.backfills.rebuild_warren_watch` was rewritten again for the trailing rule and the stop-age columns (the Gray Down and 12-month changes it used to emulate
are already applied, so that emulation is gone):

- Replays every non-removed row from `REBUILD_START` (2025-10-15 15:30) through the row's own cursor with the CURRENT rules (arrow rules plus trailing), the cached
  60m bars (no FMP call) and today's LP settings, and diffs all fourteen fields, `stop_moved_at`/`stop_moved_by` included.
- **Dry run by default**; `--apply` writes only the rows that differ and never touches `removed_at`, the cursor, `as_of` or `last_updated_at`; removed rows are
  skipped and a ticker with no row never gets one. `--show T1,T2` prints a row before/after in full.
- **Mismatch guard:** a row that differs is rebuilt only if the same bars and LP settings replayed **without trailing** (`advance(..., trail=False)`) reproduce the
  stored row exactly on the original twelve fields (the stop-age fields are excluded: stored rows hold null). Otherwise the row is printed as SKIPPED and left alone.
  **A nightly run on the new code before `--apply` writes trail moves into stored rows, and the guard then skips those rows** (no-trail replay no longer matches);
  apply the rebuild before the next 1:25 AM Warren run or expect SKIPPED lines for rows that trailed overnight.
- A dry run needs no schema change: on a database without the two columns it selects only the existing ones (`--apply` refuses until `init_db` has added them).
- Rows whose twelve original fields match but whose stop age is null count as "stop age fill only" (they are written by `--apply` too).

Dry run on the real database (as_of 2026-10-15 15:30 cursors): 114 non-removed rows, **2 identical, 112 changing, 0 skipped**; 119 s wall, 6612 LP calls (the trailing replays plus
the no-trail guard replays), 552 trail moves in total. Of the 112: **45 stop age fill only** (nothing else differs), 37 final stops change (7 of them also the basis), **53 entries
change (all later than before, none earlier)**, **17 active -> breached, 0 breached -> active**, 3 rows differ in the stop and its basis alone. After the rebuild 112 rows carry
`stop_moved_at`; the 2 null rows have no stop. Final state: active 81 (10% 61, entry 10, LP 8, none 2), breached 33 (LP 21, 10% 7, entry 5). `stop_moved_by`: yellow_up_entry 37,
yellow_up_repeat 32, trail 23, gray_down 15, blue_down 4, yellow_down 1. The 17 flips: AMZN 08-12, APH 09-02, CIBR 09-02, ETN 10-14, FTNT 09-18, HACK 09-02, IGV 08-26, ISRG 10-02, KLAC 09-14,
LLY 09-08, LMT 09-11, MRNA 09-10, NDSN 10-08, PLTR 09-28, PTC 10-14, SEZL 10-13, VEEV 08-24. This reconciles exactly with the earlier simulation (37 stops, 17 flips, 0 reverse, 53 entries, 552 trail moves).
Nightly cost afterwards: only the 8 active LP-stop rows are asked each candle, about 32 LP calls (~0.7 s) a night plus the few an arrow needs.

**Why entries jump.** A trailed stop that is hit breaches the row; the next Yellow Up on a breached row is a FRESH entry (entry kind yellow, entry = that candle's close, a new 10% stop), where
before the same row stayed "active" with an old entry. So on the 53 rows the entry price is the close of the post-breach re-entry, often far above the old one, and P/L % is measured from it.
The Entry tooltip (kind, candle, age) already says so; a row whose Stop-age tooltip reads "Set at entry" with the same stamp as the Entry cell is such a restart.

**Applied 2026-10-16** (owner approval, after the columns existed in the real DB): 112 rows written, the dry-run numbers exactly (45 stop age only, 37 stops, 53 entries, 17 active -> breached, 0 reverse, 0 skipped). A before/after dump showed exactly 112 rows changed; `removed_at`, `as_of`, `last_updated_at` and all cursors were identical on every row, and no removed row existed or was touched. A rerun reports 114 identical, 0 changing, 0 skipped.
