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
| Seed / dry run | `uv run python -m pipeline.seed_warren_watch [--dry-run]` (the same step on its own, idempotent; `--dry-run` reports and writes nothing) |
| Anchor headroom (banner data) | `anchor_headroom()` in `backend/data/warren_watch_data.py`; admin-only field `anchor_headroom` on `GET /api/technical-ideas/warren`; banner `frontend/components/technical-ideas/AnchorHeadroomBanner.tsx`; runbook "Anchor headroom and re-anchor runbook" below |
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
`instructions.py`; the API and page show the text derived from the row instead, 2026-10-19, see "Instruction texts on the Technical Ideas table"), `entry_kind` (blue / yellow / gray / null; `gray` since 2026-10-17, null only on a legacy row born from a Gray Up), `entry_at`, `entry_price` (close of the entry arrow's candle),
`stop_price`, `stop_basis` (`10%` / `LP` / `entry` / `none`), `stop_moved_at` + `stop_moved_by` (the candle that last changed the stop VALUE and the rule that did it; see "Trailing stop and stop age"), `status` (`active` / `breached`), `breached_at`, `last_signal_at`
(the latest UP arrow's candle, type 4 and Gray included), `last_updated_at` (wall-clock server time, moves only when the row's
content changes; since 2026-10-16 a trail move or a stop-age change is a content change too, so a row can now update on a candle with no arrow), `removed_at` (naive America/New_York, so it compares with candle times), `replay_from` (nullable; the removal time of a woken row, 2026-10-17), `as_of`.

## Rules at a glance (2026-10-17, updated 2026-10-18 for the LP gate and 2026-10-19 for never-lower-a-stop and the Gray Down buffer; prices are illustrative)

**Basics.** Entry = the 2h signal candle's close (not a fill). Initial stop = `0.9 x` the signal candle's low (basis `10%`; a blue entry has none). Stop basis = `10%`, `LP` or `entry`, and only `LP`-basis stops
trail. Row state = no row, **active** or **breached**. Per candle, in this order (checked in `watch.advance`): (1) the breach test against the stop as it stood BEFORE the candle, (2) the up arrow, (3) the
down arrow (judged after the up arrow, so a breached row the up arrow restarted takes the down arrow), (4) trailing. Entry and stop are always two separate numbers below.

| Arrow | No row or breached | Active row |
|---|---|---|
| **Yellow Up** | New yellow entry (entry = close, stop = `0.9 x low`, basis `10%`) | **Armed repeat Yellow:** candidate = `min(selected LP, 0.9 x candle low)`, stop = `max(current stop, candidate)` (since 2026-10-19 **no rule lowers a stop**: a candidate that is not higher changes nothing about the stop, no move, no stop-age stamp, no basis change, while the pill, text and dates still update; a row with no stop, a blue entry, takes the candidate as its first stop); entry and kind unchanged. The **first Yellow after a Blue** (within 20 candles) is no action (pill, instruction text type 4 and dates only). |
| **Blue Up** | New blue entry (entry = close, no stop) | No trade change (entry, kind, stop, basis, status stay); pill, instruction text ("BLUE UP - no change to an open trade") and dates update; resets the first-Yellow-after-Blue counter. |
| **Gray Up** | New gray entry (entry = close, stop = `0.9 x low`, basis `10%`) | No trade change; pill, instruction text (type 1, "GRAY UP - NO ACTION. Stopped out twice.") and dates update. |
| **Blue Down** | Ignored completely | stop = `max(current stop, selected LP)`; no stop yet -> the selected LP; no selected LP -> no change. Any entry kind. |
| **Yellow Down** | Ignored completely | Yellow or gray entry: stop = `max(current stop, selected LP)`; no selected LP -> no change. Blue entry: no action (pill and text only). |
| **Gray Down** | Ignored completely | Yellow or gray entry: stop = `max(current stop, entry price x 1.01)` (`GRAY_DOWN_ENTRY_BUFFER`, 2026-10-19), only if that buffered price is below the candle's close; basis `entry`, no trailing. Blue entry: no stop action (pill and text only). |

**The selected LP (2026-10-18, `WatchRules.lp_atr_gate`, trial).** Wherever a rule below says "selected LP" (repeat Yellow, Yellow Down, Blue Down, and the trailing stop) it means one definition, `watch.pick_support`, fed by `SecondSupportLookup` (`data/warren_watch_data.py`): take the kept supports below the candle close, nearest first (the Chart tab's 2h LP read, swing 2, cluster 0, **at most 3**); with **L = 1.0 x the daily ATR(14)** as of the last COMPLETED daily session strictly before the candle's date, a support is **eligible** if it is `<= close - L` (equal is eligible). Use the **2nd** support if it is eligible; otherwise walk down (the 3rd) and take the first eligible one; the **1st is never used**. If none is eligible there is no selected LP: Yellow Down, Blue Down and trailing leave the stop alone (no stop move, no stop-age update, basis unchanged; pill and text still follow the arrow) and the repeat Yellow falls back to `0.9 x low`. If the daily ATR is unavailable (no daily bars cached, or fewer than 14 completed sessions before the candle's date) the gate is off for that use and the plain 2nd LP applies; the nightly log counts those uses. Before 2026-10-18 the selected LP was always the plain 2nd-nearest support (`PREVIOUS_RULES`).

**Invariant (2026-10-17): the instruction text always follows the arrow in the pill** (Blue Up 2, or 5 in an open trade; Yellow Up 3, or 4 for a first Yellow after a Blue within 20 candles; Gray Up 1; Blue Down 10; Yellow Down 20; Gray Down 30), on every candle where the pill changes. A breached row ignores a down arrow, pill and text frozen together. No wording was added; type 4 and type 1 reuse the chart's texts. Switch: `WatchRules.text_follows_pill` (off in `PREVIOUS_RULES` / `LEGACY_RULES`, which keep the stale text so the guard reproduces stored rows).

**Trail vs arrow moves, the yellow "LP" pill (2026-10-18, display only).** On the Technical Ideas table an ACTIVE row's `LP` pill in the Stop cell turns yellow when the last stop move was a trail and no arrow has been recorded since: `stop_moved_by = trail` AND `latest_arrow_at <= stop_moved_at` (the same candle counts: the arrow is processed first, then the trail). Any later arrow clears it (`latest_arrow_at > stop_moved_at`), including an arrow that left the stop unchanged (a Blue Up on an open trade, a Gray Up on an active row, a down arrow that was a no-op); the next trail turns it on again. Not yellow when the last move came from an arrow (repeat Yellow, Yellow Down, Blue Down, Gray Down), for the `10%` and `Entry` pills, on a breached row (it shows "Stop hit"), and with no stop or no stop age. It changes no rule, stop, entry, status, sort order or instruction text, and nothing is stored: the API derives it from the stored fields (`stop_trailed_since_arrow`, see "API"). The old stop value is not stored, so the tooltip cannot show it.

**Other.** Trailing: every candle, an active `LP`-basis stop moves up to the selected LP if that is higher, never down; `10%` and `entry` stops never trail. Breached rows: P/L frozen at `(stop - entry) / entry`, no trailing, only an up arrow restarts. Stop age updates only when the stop value changes (a repeat Yellow that re-sets the same value may change the basis without stamping the age). "Ignored completely" = no pill, instruction, date or sort change. When a down arrow's level is not higher than the stop: no stop move, no stop-age update, basis unchanged, but the pill and instruction text still update.

**Edge cases** (entry, stop, event -> result; each is a test in `analysis/warren_signal/test_watch.py`, or for 15-19 `tests/test_lp_atr_gate.py`; 20-22 are 2026-10-19):

1. Entry 100, stop 90, Gray Down closes 112 -> stop 101 (100 x 1.01), basis `entry`, stop age updates (it was 100 before 2026-10-19).
2. Entry 100, stop 90, Gray Down closes 98 -> no change; closes 100.8 (the entry is below it, the buffered 101 is not) -> no change.
3. Entry 100, stop 130 (`LP`, trailed), Gray Down closes 150 -> no change (the old rule dropped it to 100).
4. Entry 100, stop 100 (an LP stop exactly at the entry), Gray Down closes 112 -> stop 101, basis `entry` (a stop at the entry is below the buffered price); a second Gray Down changes nothing, no stop-age update.
5. Blue entry, Gray Down -> pill and text only.
6. Breached row, any down arrow -> ignored completely.
7. A gray entry behaves as a yellow entry for down arrows.
8. Breach and Gray Down on one candle (entry 100, stop 101, low 100.5, close 118) -> breach first, row breached, Gray Down ignored.
9. Entry 100, stop 101 (`entry` basis), Yellow Down with 2nd LP 92 -> stop stays 101, no stop-age update, basis stays `entry`, no trailing.
10. Entry 100, stop 101, Yellow Down with 2nd LP 105 -> stop 105, basis `LP`, trailing resumes.
11. Entry 100, stop 101 (`entry` basis), armed repeat Yellow with candle low 108 and 2nd LP 104 -> candidate `min(104, 97.2)` = 97.2 is not higher than 101: ignored. Stop 101, basis `entry` and the stop age stay; the pill, text and dates update. (Before 2026-10-19 the stop dropped to 97.2, basis `10%`, and a later Gray Down lifted it back to the entry.)
12. Entry 100, stop 90 (`10%` basis), Blue Up -> nothing changes; the next Yellow Up is no action; the second Yellow acts.
13. Blue entry with no stop, Blue Down with 2nd LP 95 -> stop 95, basis `LP`.
14. Breach and Gray Up on one candle -> breach first, then the Gray Up restarts the row as a new gray entry (the breach is never shown).
15. **LP gate, 2nd LP eligible.** Entry 100, stop 90 (`10%`), Blue Down closes 120, daily ATR 5 (limit 120 - 5 = 115), supports 119 / 112 / 100 -> the 2nd (112 <= 115) is eligible: stop 112, basis `LP` (the gate changes nothing).
16. **LP gate, walk to the 3rd.** Same entry and stop, supports 119 / 116 / 110 -> the 2nd (116 > 115) is too close, the 3rd (110 <= 115) passes: stop 110, basis `LP`. A support exactly at 115 passes; at 115.01 it does not.
17. **LP gate, none eligible.** Same, supports 119 / 118 / 117 -> no selected LP: the Blue Down leaves entry 100, stop 90, basis `10%` and the stop age as they were; only the pill and text change. A trailing `LP` stop of 100 at close 120, ATR 5, with 2nd and 3rd supports 118 / 117 also stays 100.
18. **LP gate and the repeat Yellow.** Entry 100, stop 90, armed repeat Yellow on a candle with low 90, close 91, ATR 5 (limit 86), supports 90 / 88 / 60 -> the 2nd (88) is too close, the 3rd (60) passes: `min(60, 0.9 x 90 = 81)` = 60, basis `LP`. With supports 90 / 88 / 86.5 none passes -> the stop falls back to `0.9 x 90` = 81, basis `10%`.
19. **LP gate, no daily ATR** (a young ticker with fewer than 14 completed sessions, or no daily bars cached) -> the plain 2nd LP is used, as before the gate.
20. **Never lower, raised.** Yellow entry 100 (candle low 80: stop 72), armed repeat Yellow on a candle with low 100 and selected LP 75 -> candidate `min(75, 90)` = 75 > 72: stop 75, basis `LP`, stop age stamped `yellow_up_repeat`.
21. **Never lower, ignored (low or equal).** Entry 100, stop 90 (`10%`), armed repeat Yellow with selected LP 70 (candidate 70) -> stop stays 90, basis `10%`, stop age as before; the yellow LP pill rule sees `latest_arrow_at` advance while `stop_moved_at` does not. The same with a candidate of exactly 90: nothing changes.
22. **Blue entry, first stop.** Blue entry 101 (no stop), armed repeat Yellow on a candle with low 100 -> first stop 90, basis `10%` (a repeat Yellow or a Blue Down still sets the first stop).

**Where the literal wording needed a correction** (checked against the code and tests when this section was written): (a) a Gray Up on an open trade moves the pill, the instruction text (now type 1) and the dates; before the pill/text fix (2026-10-17) it moved the pill and dates but left the old text; (b) the first Yellow after a Blue is flagged by the arrow replay only within 20 candles of that Blue (`BLUE_UP_WITHIN_BARS`) and never for a gray-flavoured yellow, so a later first Yellow is an ordinary repeat Yellow; (c) "stop age updates only when the stop value changes" holds for every rule, but a repeat Yellow that re-sets the same value can still change the stop basis; (d) a down arrow on a breached row is ignored only if the same candle's up arrow did not restart the row (that down then applies to the new entry).

## Update rules

*Down arrows are gated by the show-once rule in the signal engine (each colour fires once until a non-gray Yellow Up or a Blue Up resets the flags; a Gray Up does not): see docs/specs/warren-signal.md, "Down-arrow show-once rule". The watch rows, the chart and the event log all read that one gated stream.*

*Since 2026-10-18 every "2nd LP" used for a stop in this section and below is the SELECTED LP of "Rules at a glance" (the 2nd-nearest support, gated to sit at least 1 daily ATR below the close, else the 3rd, else none); the text below was written for the plain 2nd LP, which is what the rules did before.*

Arrows are applied oldest to newest, candle by candle. On each candle the stop in force **before** that candle's arrows is
tested first, so a stop set on candle t is first tested on t+1 (the ThinkScript's `rawStopHit` needs `barsSinceYellow > 0`).

1. **Breach.** Active row with a stop and `low <= stop` -> `status = breached`, `breached_at` = the candle; stop and last
   instruction are kept. A row with no stop cannot breach.
2. **Up arrows** (one per candle: Blue, then Yellow, then Gray; a Blue on the same candle as a Yellow wins, as the ThinkScript
   resets its yellow count on a Blue). **On a BREACHED row every up arrow restarts the row as a new entry** (2026-10-17): the breach
   state, entry, stop and stop age are all replaced, as for any new entry.
   - **Blue Up** (type 2), no row / breached row / row with no entry: a **new blue entry**: entry blue, entry = this candle's close, **no stop** (`none`),
     active, stop age cleared. **On an ACTIVE row with an entry (any kind, with or without a stop) it is not an action (2026-10-17, branch
     `warren-raise-only-arrows`): entry price, date and kind, stop, stop basis, stop age and status all stay; only `latest_arrow_*`, the instruction and
     `last_signal_at` move.** The instruction becomes type 5, "BLUE UP - no change to an open trade" (the same text for every profile; it exists only
     in the watch table, `instructions.BLUE_UP_IN_TRADE`, never on the chart; before: type 2, "BLUE UP - Use appropriate stop." / "BLUE UP = ENTRY, NO STOP", which read as
     a new entry). The Blue Up **still resets the first-Yellow-after-Blue counter**: that counter lives in the arrow replay (`state_machine.py`,
     `yellow_count_since_blue`), which resets it on every Blue regardless of the table row, so the next Yellow Up is type 4 (no action) and the second
     one is an armed repeat Yellow. Before this change a Blue Up on an active yellow row replaced the entry and cleared the stop (a gray entry was the one exception).
   - **Yellow Up** (type 3), no row / breached row / row with no entry: a **fresh entry**: entry yellow, stop = `0.9 x` the arrow
     candle's low, basis `10%`.
   - **Yellow Up** on an active row with an entry (a gray entry included): stop = `min(2nd LP, 0.9 x low)`, basis whichever is lower (`10%` on
     a tie or when there is no 2nd LP). The entry is not moved, so a repeat Yellow never replaces a gray entry.
   - **Gray Up** (type 1), **no open trade** (no row, a breached row, or a legacy row with no entry): a **gray entry** (2026-10-17):
     entry kind `gray`, entry = the arrow candle's 2h close, stop = `0.9 x` the arrow candle's low, basis `10%` (stop age `gray_up_entry`),
     instruction type 1, active, `last_signal_at` = the candle. The engine's rule for when a Gray Up fires is untouched. On an **active
     row with an entry** a Gray Up changes **no entry, stop or status**: `latest_arrow_*`, the instruction (type 1) and `last_signal_at` move.
   - **First yellow after a Blue** (type 4, from the engine's `first_yellow_after_blue_at`) on an active row with an entry: no action; the
     instruction and stop stay, `latest_arrow_*` and `last_signal_at` move. With no row (or a breached one) it is a fresh yellow entry.
3. **Down arrows** (one per candle: Yellow Down, then Blue Down, then Gray Down, the ThinkScript's text order) apply only to an
   existing ACTIVE row. **On a BREACHED row a down arrow is ignored entirely** (2026-10-17): no change to the arrow pill, instruction text,
   `latest_arrow_*`, `last_signal_at`, `last_updated_at` (the content does not change), sort position, stop or status. On an active row the instruction and
   `latest_arrow_*` always update; `last_signal_at` does not. **A down arrow is raise-only (2026-10-17, branch `warren-raise-only-arrows`): a floor, never a cut.** The stop moves only on a
   row with an entry: Blue Down -> `max(current stop, 2nd LP)` (basis `LP` when it moves; a row with no stop yet takes the 2nd LP), any entry kind; Yellow Down -> the same if
   the entry is yellow **or gray**, else unchanged; Gray Down -> `max(current stop, entry_price)` (basis `entry` when it moves) if the entry is yellow **or gray** **and the entry
   price is BELOW the Gray Down candle's close** (an entry at or above the close would put the stop above the market and breach on the next candle), else unchanged; a blue entry takes
   no stop from a Gray Down at all ("GRAY DOWN on BLUE ENTRY = No Action" in the profiled scripts). **When the new level is not higher than the stop there is no change at all:** no stop move,
   no stop-age update, basis unchanged; the pill and the instruction text still update. **The ThinkScript computes no stop for a Gray Down** (its text only says "Adjust stop
   accordingly") and none that lowers a stop for a Blue/Yellow Down; this is a rule on the instruction text, like the 2nd LP. A down arrow with no row is ignored. If a candle has both
   an up and a down arrow, the up applies first, then the down; a breached row that the same candle's up arrow restarted is active when the down arrow is
   judged, so that down applies to the new entry.
   **Order within a candle is unchanged:** the breach is tested against the stop in force BEFORE the candle, then the arrows, then the trail. Consequences: a Gray (or Yellow
   or Blue) Up on the same candle as a breach finds a breached row and restarts it as a new entry, so the breach is never shown (the stopped trade is replaced by the new entry
   on that candle); a down arrow on the candle that breaches the row is ignored.
4. **No rule lowers a stop** (2026-10-19; until then the armed repeat Yellow Up was the ONLY rule that could): a second Yellow whose `min(selected LP, 0.9 x low)`
   is not above the current stop changes nothing about the stop. Blue Down, Yellow Down, Gray Down (since 2026-10-17) and the trail below are raise-only too.
5. **Trailing (2026-10-16).** After a candle's arrows, an ACTIVE row whose stop basis is `LP` takes the 2nd LP as of THAT candle; if it is higher than the
   stop, the stop is raised to it (basis stays `LP`). It never lowers a stop, never trails a `10%`, `entry` or `none` stop, and does not touch a breached row.
   It runs on every 2h candle the row reads, arrow or not. The breach test on a candle uses the stop as it stood BEFORE that candle (rule 1), so a stop trailed on
   candle t is first tested on t+1. Consequence: a trail that is hit on the next candle breaches, and the next Yellow Up then creates a FRESH entry (a
   breached row restarts), so entry prices on trailed rows jump.

### Trailing stop and stop age

`stop_moved_at` (naive ET candle start) and `stop_moved_by` record the last change of the stop VALUE: `yellow_up_entry` (fresh entry), `yellow_up_repeat`,
`blue_down`, `yellow_down`, `gray_down`, `trail`, `gray_up_entry` (a Gray Up entry, 2026-10-17). Re-setting the same value is not a move (a Blue Down whose 2nd LP equals the stop changes the text and the basis
at most, not the stop age); a stop that becomes none (a Blue Up restarting a breached row as a blue entry) clears both; a fresh entry always stamps them. Both are nullable
(`_add_missing_columns` adds them on startup); a row not yet rebuilt shows no stop age. They are part of the row's content (`_content`), so a trail changes
`last_updated_at`.

**LP cost.** Trailing asks for the 2nd LP only for an ACTIVE row with an `LP` stop, on every candle it reads (the full `compute_liquidity_zones_2h` slice, never
the pivot-only shortcut, which gives different results). Rows on a `10%`/`entry`/`none` stop and breached rows cost nothing. The lookup caches by candle, so an
arrow candle that also trails asks once. A normal night reads at most 4 new candles per ticker, so about 4 LP calls (~22 ms each) per active LP-stop row.

**Gray Down raise-only (2026-10-17, on main).** Before it, a Gray Down set the stop to the entry price even when that LOWERED a higher stop (RMD 07-06: LP 192.84 -> entry 186.52; 10-15: repeat-Yellow 196.87 -> 186.52). `WatchRules.gray_down_raise_only` carries the previous behaviour. **Rule switches (branch `warren-raise-only-arrows`):** `CURRENT_RULES` = every switch on; `PREVIOUS_RULES` = the rules on main before the raise-only down arrows / Blue Up no-op change (`blue_up_in_trade_no_op=False`, `down_arrows_raise_only=False`; what the stored rows were built under, the rebuild guard's `GUARD_RULES`); `PRE_GRAY_RAISE_ONLY_RULES` = `PREVIOUS_RULES` with `gray_down_raise_only=False`; `LEGACY_RULES` = every switch off (before the gray-entry change). Repeat Yellow ("whichever is lower") and trailing are unchanged.

**Gray-entry rows** follow the yellow-entry rules afterwards (rule 3 above: Gray Down, Yellow Down, Blue Down, repeat Yellow, trailing, breach, P/L %); the `gray` kind stays for the life of the trade, a 10%- or entry-basis stop never trails. Only a breach followed by an up arrow ends the trade.

**2nd LP** = the second-nearest support below the **close of the arrow candle**, from `compute_liquidity_zones_2h` (the Chart tab's
2h LP read) over the candles up to and including that candle, with the **shared LP settings as they are** (`LiquidityZoneSettings`;
`breach_recency_bars` is the 2h override, irrelevant for supports). It is asked for only where a rule needs it: a Yellow Up on an
active row, a Blue Down, a Yellow Down on a yellow or gray entry, and (2026-10-16) every candle of an active LP-stop row for the trail. No LP is computed for a fresh entry, a Blue Up, a Gray Down or a
no-action arrow on a row that does not hold an LP stop. **Dependency:** the engine returns at most `max_lps_per_side` supports (3 today), so the 2nd LP exists only if that
setting is 2 or more; with fewer than two supports (or a setting of 1) the 2nd LP is "none" and the rules fall back as above (a
Yellow keeps the `10%` stop; a down arrow leaves the stop). A settings edit changes later stops, never stored ones.

## Stateless nightly replay (2026-10-17), the cursor and idempotence

**Every night each monitored ticker's row is recomputed from scratch**: all completed 2h candles after `REPLAY_ANCHOR` (a FIXED 2025-10-15 15:30, the first seed's as_of minus 12 months) are replayed on the 60m bars the Warren job just read from the shared cache (no extra download), and the stored row is rewritten only if the result differs (`last_updated_at` moves only then). This replaced the cursor design, which folded each session in once from the provisional bars FMP serves the night right after it and never looked at those candles again (RMD, ADP and ROBO kept arrows and prices the final bars no longer give; see the open items). `WarrenWatchCursor` (`ticker`, `processed_through`, `updated_at`) is now bookkeeping only: the page's "as of" is its newest `processed_through`.
- **Anchor, not a sliding window.** A window that slides with the date would change the state of an open trade as it moves (the entry would jump to the next up arrow once the trade is 12 months old). The anchor is a constant, so the window grows from 12 months. **It must be moved forward before the cached 60m history (730 days) leaves under 180 days of warm-up before it (2027-04-17 at the current anchor). An admin banner on the page warns from 2026-12-19; the steps are in "Anchor headroom and re-anchor runbook" below.**
- **Row creation (unchanged):** a ticker with no row gets one only if an up arrow (Blue, Yellow or Gray) fell in the LAST 3 months (`ROW_MONTHS`, `_has_recent_up`); the whole replay decides its state, so it starts with the full history (a ticker that gained its first recent up arrow later is no longer "fresh from that arrow": its state is what the replay gives). A down arrow with no earlier up arrow creates nothing. A new ticker entering the monitored lists is handled the same way the night it appears (it needs its 60m history in the cache, as before); a young ticker is replayed from whatever history it has.
- **A row whose replay gives nothing** (history revised away) is kept as stored and never deleted.
- **Removal is preserved:** a removed row is replayed only from `removed_at` on and stays removed until an up arrow falls after it; the woken row is rewritten fresh with `removed_at` cleared and **`replay_from` = the removal time** (new nullable column, added by `init_db`'s additive column sweep), so later nights replay from there and the pre-removal trade does not come back.
- **Idempotent:** a second run on the same bars writes nothing but an unchanged `as_of`/cursor (test-pinned: the tables are identical, `last_updated_at` included). A missed night costs nothing: the next replay sees every candle.
- **Warm-up.** The replay uses the WHOLE cached 60m history (`LOOKBACK_DAYS` = 730) and applies only what falls after the anchor, so the engine has about a year before it as warm-up. The 180-day `EVENT_WRITE_WARMUP_DAYS` buffer belongs to the stored `WarrenSignalEvent` writes and is not part of this path (unchanged). A ticker whose first candle is later than anchor minus 180 days has a thinner warm-up (AIPO, 283 days of history).
- A ticker that leaves the monitored lists is no longer processed; its row stays as it was.
- **Dry run:** `uv run python -m pipeline.seed_warren_watch --dry-run` replays every monitored ticker from the cache with the network blocked in practice (cache read only, no FMP call, no top-up), never runs `init_db` and never creates a settings row, and prints what it WOULD create or change (field by field) without writing anything. It reads a database that has not got `replay_from` yet.
- **Cost (measured 2026-10-17 on the live data, 136 tickers, no network):** about 128 s, almost all of it 8,123 `compute_liquidity_zones_2h` calls (trailing asks an LP-stop row on every candle after its stop was set, so a row's cost grows with its age); the candles and arrows take 6 s. The Warren job took about 150 s before; it now takes about 280 s, still finishing around 1:30 AM before the next job (1:35). If it grows, memoise the LP per (ticker, candle) or move the anchor forward.

## Anchor headroom and re-anchor runbook (2026-10-18)

### Headroom and the banner

**Headroom** = days of cached 60m history before the replay anchor = `REPLAY_ANCHOR` date minus the first date of the nightly slice (`data/warren_watch_data.py::anchor_headroom`; the slice start is the nightly step's own, `pipeline/backfills/reconcile_warren_events.py::nightly_bars_start` = Eastern today minus `LOOKBACK_DAYS - 1`, so it follows `LOOKBACK_DAYS`). It is a calendar-day count from the slice's first DATE; the first candle is the first session on or after it (up to 3 days later), so the figure can read up to 3 days high. A pure computation: no DB, no FMP, no clock but the `now` it is given. **361 days on 2026-10-18** (anchor 2025-10-15, slice start 2024-10-19).

| Level | Rule | First day (anchor 2025-10-15 15:30) | Why |
| --- | --- | --- | --- |
| none | 300 days or more | until 2026-12-18 | |
| warning | under 300 days | 2026-12-19 | time to plan; banner appears |
| urgent | under 270 days | 2027-01-18 | the sliding-start test (2026-10-18) first saw arrows flip at 270 days (BKNG's Gray Up read as Yellow Up: a carried latch, not indicator drift) |
| hard deadline | 180 days reached | 2027-04-17 | the event write gate's warm-up (`EVENT_WRITE_WARMUP_DAYS`); below it more rows change (21 tickers' arrows at 60 days, UNH's row at 60 days because its 2nd LP vanishes) |

**API.** `GET /api/technical-ideas/warren` returns `anchor_headroom` = `{days, level: "warning"|"urgent", anchor, slice_start, warning_date, urgent_date, deadline_date}` for an **admin** when the level is not none, else `null` (a viewer gets `null` and the function is not even called; `core/main.py` `technical_ideas_warren`, schema `AnchorHeadroomOut` in `core/schemas.py`). No schema change to any table, no write.

**Banner.** `components/technical-ideas/AnchorHeadroomBanner.tsx`, directly below the page title on `/technical-ideas`, behind `<AdminOnly>`, drawn only at warning or urgent. It says the replay start date is running out of warm-up history, the headroom in days, the urgent date (past tense once urgent) and the hard deadline, and "Re-anchor: see the runbook in docs/specs/warren-signals-page.md". Warning uses the app's `warn` notice box (as `DataQualityNote`), urgent the `negative` one (as `FmpHealthSummaryCard`) with `role="alert"`; no dismiss button. It clears by itself once the headroom is 300 days or more again (after the anchor is moved AND the app restarted, because the app reads the constant at start). Tests: `tests/test_anchor_headroom.py`, `components/technical-ideas/AnchorHeadroomBanner.test.tsx`, `app/technical-ideas/page.test.tsx`.

### Why the anchor stays fixed (decision 2026-10-18)

A sliding start was tested on the live data (2026-10-18, report-only, bars unchanged): the first 90 one-day slides changed no row, but from there on 14 changes on 9 rows in 90 nights, every one a trade that was OPEN at the new start being forgotten and the entry replaced by a later or different one (UNH flipped on night 110 and back on 111, ALLE changed five times); a single +180-day slide moves 7 of 117 rows (6%) with P/L swings of 3 to 12 points. The fixed anchor keeps every row's trade chain intact and moves rarely, by hand, with a backup and a dry run. Rejected: the sliding start (forgets trades open at the start), a carried-state checkpoint (the old cursor design in disguise, built on bars FMP still revises; it would need a stored per-ticker snapshot and a rebuild that the 730-day bars could no longer reproduce), and a log line instead of a banner (nobody reads the cron log in December). Raising `LOOKBACK_DAYS` is the alternative that buys room without moving the anchor (below).

### Re-anchor runbook

Every command below is run by you, from the main checkout unless it says otherwise. Replace `<ts>` with the timestamp you used. **Read steps 4 and 5 first: editing the constant in the main checkout is itself the apply.**

**1. When, and the pre-checks**
- The banner appears under 300 days (2026-12-19 at the current anchor). Do it **before 270 days (2027-01-18)**, never later than 180 days (2027-04-17). Target: the week of 2026-12-21.
- A good moment: a Sunday daytime UTC (no session bars arrive between the dry run and the apply, and the Saturday 04:00 and 06:00 weekly jobs are long done), or any weekday between 03:40 and 14:00 UTC (after the nightly chain and backup, before the first completed candle of the US session at about 15:30 UTC). **Time guard: never between 01:05 and 02:30 UTC** (the Warren cron starts 01:25 and the chain runs to about 03:35, with the 03:30 backup).
- `date -u` (outside the guard); `pgrep -af "pipeline\."` prints nothing (no job running); `crontab -l | grep -c pipeline` unchanged from `backend/crontab.txt`; `curl -s localhost:8002/api/health` is 200.
- **Disk:** `df -h /` must show at least 1.7 GB free (the full copy is about 1.41 GB, 343,912 pages x 4096 B on 2026-10-18, plus slack). If short, free space first, biggest first and check each before deleting: stale VS Code server builds under `~/.vscode-server/bin/` (about 650 MB each, 3.8 GB in `~/.vscode-server` on 2026-10-18; keep the newest, `ls -dt ~/.vscode-server/bin/*`), ad-hoc snapshots in `~/scratch` and `$HOME` (`ls -la ~/*.db ~/scratch/*.db 2>/dev/null`; see `backend/OPS_RUNBOOK.md`, "Disk space"). Do NOT touch `backend/backups/` (the restore points) or `frontend/.next` (the live build). The two empty `backend/fathom_pre_rebuild4_20261017_083559.db-shm/-wal` stubs are safe to delete but free nothing.

**2. Full DB backup (SQLite online backup) and its verification**

    python3 - <<'PY'
    import sqlite3, time
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = f"/home/shen/backups/fathom_pre_reanchor_{ts}.db"
    src = sqlite3.connect("file:/home/shen/fathom/backend/fathom.db?mode=ro", uri=True)
    dst = sqlite3.connect(path)
    src.backup(dst); dst.close(); src.close()
    print(path)
    PY
    chmod 600 /home/shen/backups/fathom_pre_reanchor_<ts>.db

Verify (write down the numbers in the aftercare note):

    ls -la /home/shen/backups/fathom_pre_reanchor_<ts>.db      # about 1.41 GB
    python3 - <<'PY'
    import sqlite3
    for name, uri in (("live", "file:/home/shen/fathom/backend/fathom.db?mode=ro"), ("backup", "file:/home/shen/backups/fathom_pre_reanchor_<ts>.db?mode=ro")):
        c = sqlite3.connect(uri, uri=True)
        print(name, "pages", c.execute("PRAGMA page_count").fetchone()[0], "journal", c.execute("PRAGMA journal_mode").fetchone()[0],
              "watch rows", c.execute("select count(*) from warrenwatchrow").fetchone()[0], "cursors", c.execute("select count(*) from warrenwatchcursor").fetchone()[0])
    c = sqlite3.connect("file:/home/shen/backups/fathom_pre_reanchor_<ts>.db?mode=ro", uri=True)
    print("quick_check", c.execute("PRAGMA quick_check").fetchone())      # takes a minute or two; must print ('ok',)
    PY

Expect: size about page_count x 4096, journal `wal` on both, watch rows 117 (non-removed plus removed, today) and cursors 136 equal on both (a few pages' difference is only a write between the two reads), `quick_check` `('ok',)`. **Keep the backup until two clean nightly runs have passed after the apply (step 9), then delete it.** The ordinary nightly backup (03:30, `backend/backups/fathom_*.db.gz`, 3 daily + 4 weekly) is a second restore point but loses the writes of the nights since.

**3. Choosing the new anchor**
- Move it later by about 180 days, to a 2h candle window START on a regular full session day. The code expects a naive America/New_York `datetime` that equals a candle index value: `09:30`, `11:30`, `13:30` or `15:30`. Use `15:30` like the current one (the replay applies the candles AFTER the anchor, so a 15:30 anchor starts the replay at the next session's 09:30 candle), on a normal trading day (not a holiday, and a day whose 15:30 window exists: not an early-close day). Example for a December 2026 run: `datetime(2026, 4, 13, 15, 30)` (a Monday, old anchor + 180 days).
- **Constraint:** the new anchor must leave at least about 300 days of headroom on the day you apply it, and should stay a few months in the past (a ticker whose newest arrow is not after the anchor has no state to replay, see step 6). Check before editing anything else: `cd <checkout>/backend && /home/shen/fathom/backend/.venv/bin/python -c "from datetime import datetime; from data.warren_watch_data import anchor_headroom; h = anchor_headroom(anchor=datetime(2026, 4, 13, 15, 30)); print(h.days, h.level, h.warning_date, h.urgent_date, h.deadline_date)"` (run from the worktree of step 5; `days` must be 300 or more). A later anchor buys more runway (about 1 day per day) and changes more rows; a 180-day move buys 180 days.
- **Expected effect** (sliding-start test, 2026-10-18, +180 days on the live data): about 6 to 8% of the 117 rows change (7 rows: A, ADP, ASML, FIX, GD, MCD, NOC), almost all through the entry (entry kind, date and price) because a trade open at the new anchor is forgotten and the next up arrow opens a new one; the stop, status, pill, text and P/L follow. **Upper bound about 76%**: 89 of 117 rows had a trade open at that start, so a surprise well above 10% means the dry run is showing something other than the plan (step 6). Rows without a trade open at the new anchor do not change.

**4. How the anchor is read (verified in the code 2026-10-18)**
- **Since the LP gate (2026-10-18) the replay also reads the cached DAILY bars of every ticker** (for the ATR); a dry run, the apply and the nightly all do, with no network call. Keep them cached through a re-anchor.
- **Defined once:** `backend/data/warren_watch_data.py:53`, `REPLAY_ANCHOR = datetime(2025, 10, 15, 15, 30)` (comment above it, lines 50-52).
- **Read by:** `update_warren_watch` (`data/warren_watch_data.py:183`, `after = REPLAY_ANCHOR`), which is the nightly step (`update_watch_table`, `pipeline/nightly_warren_signal_calculation.py:79`, called at line 194) and `pipeline.seed_warren_watch` (the same function, dry or for real); `pipeline/backfills/rebuild_warren_watch.py:45` (`REBUILD_START = REPLAY_ANCHOR`, at import); `anchor_headroom()` (the banner, in the app process, so the app needs a restart to see a new value).
- **Per-row override:** `after = max(REPLAY_ANCHOR, row.replay_from, row.removed_at)` (lines 183-186). `replay_from` is set only when a removed row is woken (`replay_from` = the removal time). On 2026-10-18 it is NULL on all 117 rows (and none are removed), so nothing overrides the anchor; check again before the run: `python3 -c "import sqlite3; c=sqlite3.connect('file:/home/shen/fathom/backend/fathom.db?mode=ro',uri=True); print(c.execute('select count(*) from warrenwatchrow where replay_from is not null or removed_at is not null').fetchone())"`. A row with a `replay_from` or `removed_at` LATER than the new anchor keeps replaying from that time; one earlier than it follows the new anchor.
- **Not read:** `WarrenWatchCursor` (`processed_through` only feeds the page's "as of"; nothing to change), the `WarrenSignalEvent` log (its write gate is the slice's first candle plus 180 days, independent of the anchor), the chart. The arrow replay itself always runs on the whole 730-day slice; the anchor only decides where the trade state starts.
- **Tests that pin the old value** (update them in the same commit): `tests/test_rebuild_warren_watch.py:47` (`rb.REBUILD_START == datetime(2025, 10, 15, 15, 30)`) and the literal dates around the anchor in `tests/test_warren_watch_data.py:84-103` (the `ANCIENT` and `CUT12` cases).

**5. The order that keeps the nightly cron from applying it by itself**
- **Verified: yes, it would.** The cron line is `cd /home/shen/fathom/backend && ... uv run python -m pipeline.nightly_warren_signal_calculation` (`backend/crontab.txt` line 79), so it imports whatever is in the main checkout's working tree at 01:25 UTC: a COMMITTED or merely SAVED edit of line 53 counts, there is no deploy step. `update_watch_table` then calls `update_warren_watch` for every ticker with no dry-run flag and no guard, and rewrites every row whose result differs. So a changed constant left in the main checkout when 01:25 comes is applied tonight, with no review (the app is not involved; the nightly would also leave the Warren event log alone, but the watch rows would all move).
- The `pipeline.backfills.rebuild_warren_watch` script cannot do this job: it is built for a RULE change. Its mismatch guard replays the PREVIOUS rules (`GUARD_RULES = PREVIOUS_RULES`) from the new anchor and skips every row they do not reproduce, which after a re-anchor is every changing row, so `--apply` would write almost nothing. Use `pipeline.seed_warren_watch`.
- **Safe order (all in one sitting, inside a window that does not touch 01:05-02:30 UTC):**
  1. Make a branch and a worktree; the main checkout stays untouched: `cd /home/shen/fathom && git worktree add /home/shen/fathom-warren-reanchor -b warren-reanchor main`.
  2. In the worktree, edit `backend/data/warren_watch_data.py:53` (and update the comment above it), update the two tests of step 4. Run `cd /home/shen/fathom-warren-reanchor/backend && /home/shen/fathom/backend/.venv/bin/python -m pytest tests/test_rebuild_warren_watch.py tests/test_warren_watch_data.py tests/test_anchor_headroom.py -q` (the main checkout's interpreter, run from the worktree, imports the worktree's code; do not `uv run` there: it would build a new environment).
  3. Take the backup (step 2). Run the dry run from the worktree (step 6). The worktree has no database of its own: point it at the live one with `DATABASE_PATH`.
  4. Only if the dry run is accepted: commit on the branch, then merge into main and apply in the same minute: `cd /home/shen/fathom && git merge --ff-only warren-reanchor && cd backend && uv run python -m pipeline.seed_warren_watch` (step 7). **Do not stop between the merge and the apply, and finish before 01:05 UTC**: after the merge the cron would apply the same change anyway, and if you applied from the worktree but did NOT merge, the 01:25 run (old constant on main) would rewrite the rows back.
  5. If the dry run is not accepted: remove the worktree and branch, and nothing has changed: `git worktree remove --force /home/shen/fathom-warren-reanchor && git branch -D warren-reanchor`.

**6. The dry run, and how to read it**

    cd /home/shen/fathom-warren-reanchor/backend
    DATABASE_PATH=/home/shen/fathom/backend/fathom.db /home/shen/fathom/backend/.venv/bin/python -m pipeline.seed_warren_watch --dry-run

It reads the cached 60m bars only (no FMP call, no top-up), never runs `init_db`, never creates a settings row and writes nothing; about 2 minutes and 8,000 LP calls on the live data (122-128 s measured on 2026-10-17/18), and it fits next to the running app. (Its bars window starts at today minus 730 days, one day wider than the nightly's 729; no effect on the result. The `DATABASE_PATH` resolution to the live file was checked on 2026-10-18; the dry run itself was not run for this runbook.) Output:

    DRY RUN (nothing written): 136 tickers, 0 would be created, N would change, 0 failed; ... LP calls; ...s
      TICKER: changed
          entry_kind: blue -> yellow
          entry_at: 2026-02-12 11:30:00 -> 2026-06-23 09:30:00
          entry_price: 209.15 -> 219.44
          stop_price: ...
          status: ...

Per changed row the lines are `field: stored -> new` for the 14 state fields (entry kind, entry time, entry price, stop, stop basis, status, latest arrow kind and time, instruction type, last signal, stop age, breach time). **P/L is not printed**: compute it for the rows you care about, active = (last close - entry) / entry, breached = (stop - entry) / entry (the page shows it after the apply).
- **Read it like this:** N should be about 6 to 8% of the rows (7 to 9 of 117); each changed row should show a later (sometimes earlier) `entry_at` and `entry_price`, usually with the stop and status that follow from the new trade. Rows that do not have a trade open at the new anchor must not appear.
- **Stop conditions (do not apply; remove the worktree and look):** N above about 15 (13%); any `would be created` (the plan creates no rows); any `FAILED`; any row that changes WITHOUT a new `entry_at` or `entry_price` (a row whose trade was not forgotten should not move); an `active -> breached` or `breached -> active` flip on a row whose entry did not change; or any row you cannot explain as "a trade open at the new anchor was forgotten and the next up arrow opened a new one". Also stop if the stored rows are not the baseline you expect: run the dry run once on the UNCHANGED main checkout first (it must print `0 would change`).
- **Rows the dry run cannot show:** a stored row whose newest arrow is not after the new anchor has no state to replay, so the step keeps the stored row as it is (never deletes it) and lists nothing. List them before applying (use the new anchor's date): `python3 -c "import sqlite3; c=sqlite3.connect('file:/home/shen/fathom/backend/fathom.db?mode=ro',uri=True); print(c.execute(\"select ticker, entry_at, latest_arrow_at, status from warrenwatchrow where removed_at is null and latest_arrow_at <= '2026-04-13 15:30:00'\").fetchall())"`. Each one stays on the page showing a trade older than the new anchor; decide per row (accept, or remove it from the page: `DELETE /api/technical-ideas/warren/{ticker}`). Expected today: none (the sliding-start test found 0 such rows at +180 days).

**7. Apply, post-apply dry run, table check, restart**
- Apply (main checkout, after the merge of step 5; this is the nightly step run by hand: it reads the cache through the normal path, so it may top up a few bars from FMP and it runs `init_db`): `cd /home/shen/fathom/backend && uv run python -m pipeline.seed_warren_watch` (about 2 to 3 minutes). It prints the summary dict; `watch_changed` must equal N of the dry run, `watch_created` 0, `watch_failed` 0. If a session candle completed between the dry run and the apply, `watch_changed` can be a row or two higher: re-run the dry run, do not guess.
- **Post-apply dry run, expect 0:** `cd /home/shen/fathom/backend && uv run python -m pipeline.seed_warren_watch --dry-run` must print `0 would be created, 0 would change, 0 failed`.
- **Table check:** the rows named in the dry run (open the page, or `select ticker, entry_kind, entry_at, entry_price, stop_price, status from warrenwatchrow where ticker in (...)`); and that no row is older than the anchor: `select ticker, entry_at from warrenwatchrow where removed_at is null and entry_at <= '2026-04-13 15:30:00'` returns nothing but the stale rows you already accepted in step 6. Row count unchanged (117 non-removed, 136 cursors).
- **Restart (the app reads the constant for the banner):** the rows are in the database, so the page shows them without a restart, but the banner (and any viewer-served code) only changes after one. Follow `backend/OPS_RUNBOOK.md`, "Starting / stopping the app": **check `date -u` is outside 01:05-02:30 first**, then `cd /home/shen/fathom && ./bin/stop.sh && ./bin/start.sh --prod` (it rebuilds the frontend, a few minutes; it runs in the foreground, so use a terminal you keep open or `setsid nohup ./bin/start.sh --prod > /tmp/fathom_start.log 2>&1 &`). Check `curl -s -o /dev/null -w "%{http_code}\n" localhost:8002/api/health` is 200, the warren route answers 401 unauthenticated, `grep -ci error backend/logs/uvicorn_dev.log` has nothing new, and `crontab -l | grep nightly_warren` still shows `25 1 * * *`. **`./bin/stop.sh` takes no arguments and stops the live app whatever you pass it.**

**8. Rollback**
- **Revert and rebuild from the cached bars (cheap; keeps every other write since the backup):** `cd /home/shen/fathom && git revert <the merge or commit>` (restores the old constant), then `cd backend && uv run python -m pipeline.seed_warren_watch` (about 3 minutes) rewrites the rows from the old anchor, and a restart as in step 7. It works only while the old anchor still has its 180 days of warm-up in the slice (until 2027-04-17 for the current anchor); it does not use `rebuild_warren_watch` (step 5). Rows then equal what they were before, because the replay is stateless.
- **Restore the backup (last resort; costs every database write since the backup, including the nightly runs of those days, user edits to watchlists and removed rows):** 1) `crontab -l > ~/crontab.saved && crontab -r` (no job may start); `pgrep -af "pipeline\."` empty. 2) `cd /home/shen/fathom && ./bin/stop.sh`; `lsof backend/fathom.db` prints nothing. 3) `mv backend/fathom.db /home/shen/backups/fathom_bad_<ts>.db && rm -f backend/fathom.db-wal backend/fathom.db-shm` (the old -wal/-shm must not sit next to the restored file). 4) `cp /home/shen/backups/fathom_pre_reanchor_<ts>.db backend/fathom.db && chmod 600 backend/fathom.db` (needs the 1.41 GB of step 1 free again for a while). 5) `python3 -c "import sqlite3; print(sqlite3.connect('file:backend/fathom.db?mode=ro', uri=True).execute('PRAGMA journal_mode').fetchone())"` prints `('wal',)`. 6) Put the code back (revert as above, or `git checkout` the old commit), `./bin/start.sh --prod`, then `cd backend && crontab crontab.txt` and `crontab -l` against the file. 7) Delete `fathom_bad_<ts>.db` when satisfied. See "Restoring an old backup" in `backend/OPS_RUNBOOK.md` (WAL section).

**9. Aftercare**
- After **two clean nightly runs** (the Warren log line `grep "Warren watch table updated" backend/logs/nightly_warren_signal_calculation.log | tail -2` shows `Failed: 0` and a `Changed:` count in line with an ordinary night, a handful at most, and `GET /api/config/cron-health` shows the Warren job ok): `rm /home/shen/backups/fathom_pre_reanchor_<ts>.db`. Remove the worktree and branch if the branch was merged: `git worktree remove /home/shen/fathom-warren-reanchor && git branch -d warren-reanchor`.
- Update this spec: the new anchor value, the date, the number and names of rows changed, the dry run and apply summaries, the backup numbers; the deadline dates in "Open for a later phase" (they move by the length of the move); the sentence in "Stateless nightly replay"; and the comment above `REPLAY_ANCHOR`. Add a `docs/decisions.md` line only if the plan changed.
- **The banner resets itself**: once the app is restarted on the new constant the headroom is back above 300 days and the field is `null`.

**10. The alternative to more room: a longer `LOOKBACK_DAYS` (not built, only described)**
Raising `LOOKBACK_DAYS` above 730 (`pipeline/nightly_warren_signal_calculation.py:74`, "our own fetch choice, not an FMP limit") would keep the anchor in place longer without moving any row. It needs: a refetch of the 60m history for every ticker (FMP serves several years of 1hour bars; about 162 tickers on the monitored lists and ETFs), because the cache holds only about 391 days before the anchor now (the first bars date from 2024-09-19); the shared cache's "2y" tier and the width tests (`RETENTION_DAYS`) move; **the Chart 2H range's lookback is pinned equal to it** (`data/chart_data.py` `RANGE_CONFIG["2H_90D"]`, test-pinned), so the chart's on-demand replay changes; and **the event write gate moves earlier by the added days** (first candle + 180), so the first nightly after the change reconciles NEW events into the log for the added period (consumers: chart markers, Opportunities B3 and D1 flags, the score fields), which needs the same review as the 2026-10-18 event reconcile. It also adds rows: the 60m cache holds 577,883 rows of the 1.41 GB database today, so a third year costs roughly another half of that, and the nightly job reads and replays more bars (the LP cost grows with the history). Disk is tight (about 2.8 GB free on 2026-10-18; a full backup needs 1.5 GB), so check `df -h /` first. Not recommended as the first move: re-anchoring costs a 30-minute sitting twice a year; this costs a design review.

## LP gate: daily ATR x1, reading R1 (2026-10-18, adopted as a trial on main)

**Rule.** See "The selected LP" under "Rules at a glance". Switch `WatchRules.lp_atr_gate` (default on). `PREVIOUS_RULES` was then the current rules with the gate off (since 2026-10-19 it is the rules with the gate ON and never-lower / the Gray Down buffer off, and `PRE_LP_GATE_RULES` is the gate-off set); the rules before the raise-only change moved to `PRE_RAISE_ONLY_RULES`; `PRE_GRAY_RAISE_ONLY_RULES` and `LEGACY_RULES` have the gate off.

**ATR definition.** `analysis/warren_signal/indicators.py::compute_atr_wilder` (the repo's helper, also used by the Chart tab's FVG filter), length 14, on the completed daily bars: Wilder smoothing (`wilder_rma`: a simple average of the first 14 true ranges, then `(prev x 13 + TR) / 14`) of the true range `max(high - low, |high - previous close|, |low - previous close|)`, so the overnight gap is included. The what-if used exactly this helper, so the definition is not a guess. The value for a candle is the ATR of the last completed session strictly before the candle's date (`daily_atr_for_candles`, `searchsorted(..., side="left") - 1`): the candle's own session is not used even once it has closed, and a later daily bar can never change an earlier candle (a test pins it).

**Entry points.** The nightly step, `pipeline.seed_warren_watch` and the rebuild script all replay through `SecondSupportLookup`, so they use the same gate. `advance` reads `rules.lp_atr_gate`: with it off it uses the lookup's `.plain` (the ungated 2nd LP); a plain callable (tests) is used as it is.

**Rebuild guard after this change.** `GUARD_RULES = PREVIOUS_RULES` is now "current rules, gate off". It is meaningful for exactly one thing: rows still held under the gate-off rules (it reproduces them, so a dry run of `rebuild_warren_watch` before the first gated nightly run would apply the gate to them). Once the nightly step has written rows under the gate, the guard no longer reproduces them and every changing row is skipped, so the script cannot rebuild anything after that; use `pipeline.seed_warren_watch` (the nightly step). The re-anchor runbook already says the same for a different reason; it now also depends on the cached daily bars (a ticker without them is replayed gate-off, which changes its rows compared with a night that had them).

**Evidence (what-if of 2026-10-18, report-only, 136 tickers, 2025-10-15 to 2026-10-16, equal-risk R, not a dry run of this code).** R1 with 1 x daily ATR: realized R +243.5 -> +262.5 (+19.0), profit factor 2.85 -> 2.96, expectancy 0.690 -> 0.752, average win 2.19R -> 2.35R, trades 450 -> 446, combined (with unrealized) +252.4 -> +271.5; mean hold 57.6 -> 62.2 days, trades over 180 days 17 -> 19. The gate fired on 9.7% of arrow-time LP uses and 22% of trailing uses (2.9% and 6.7% with no eligible LP). **Not robust enough to call it an edge:** the gain sits in the first half of the year (entries before 2026-04-15: +18.0R; second half +1.0R), per ticker 36 up against 47 down (sign test p = 0.27) with the bootstrap interval of the mean change barely above zero, concentrated in a few runners (MU, SEZL, STX, WDC), and tail losses were NOT reduced (R < -1: 25 -> 27 trades, worst trade unchanged at -3.54R, 10%-stop exits untouched). Wider multiples and the fixed-percentage limits looked better only through open trades marked at the last close and are not adopted. Re-measure after a down or sideways stretch.

**Expected effect on the table (unverified).** No dry run was run before the merge. The what-if suggested about 16 of the 117 rows would change on the next nightly run: status PTC; entry ETN, NDSN, LMT; stop ETN, AMAT, GOOGL, KLAC, FIX, FTNT, VEEV, PTC, AMZN, KEYS, CRDO, PLTR, LMT, COHR, IGV. The production code was not compared with the what-if row by row, and the daily-bar read in production differs in two small ways (a 1400-day cache read at run time; the provisional newest session dropped by the reader).

## Never lower a stop and the Gray Down buffer (2026-10-19)

**Rules** (switches `WatchRules.never_lower_stop` and `WatchRules.gray_down_entry_buffer`, both default on; the constant `GRAY_DOWN_ENTRY_BUFFER = 0.01` is defined once in `analysis/warren_signal/watch.py`; no setting, no UI):
- **A, never lower a stop.** On an ACTIVE row that has a stop, a repeat Yellow Up sets stop = `max(current stop, candidate)`, the candidate staying `min(selected LP, 0.9 x candle low)`. A candidate that is not higher (lower or equal) changes nothing about the stop: no `stop_moved_by` / `stop_moved_at`, no basis change. The arrow itself still applies (pill, text, `latest_arrow_at`, `last_signal_at`, the first-Yellow-after-Blue counter). A row with no stop (blue entry) still gets its first stop from a repeat Yellow or a Blue Down; a breached row restarts as a fresh entry with a 10% stop on the new low; the first Yellow after a Blue within 20 candles stays no action.
- **B, Gray Down buffer.** On an active yellow/gray-entry row, Gray Down sets stop = `max(current stop, entry x 1.01)` only if that buffered price is below the candle close (the old test was entry below close). Basis stays `entry` (so no trailing), `stop_moved_by` stays `gray_down`. Blue entries: no stop action. A stop exactly at the entry is therefore raised by a later Gray Down.
- **C unchanged.** The LP multiple stays 1.0 x daily ATR(14). No multiple was consistent across the two halves of the year, and a settings section was not built on purpose: a live setting would rewrite every row's history at the next run.

**Evidence** (phase 1 what-if, 2026-10-19, report only, 136 monitored tickers, 446 trades under the old rules; R as in the LP gate section; the what-if assumed free re-entries after a stop-out):
- A alone: realized +8R (270.7 vs 262.5, 95% interval -29 to +56 over tickers), first half +21R, second half -13R: inside the noise. It is a risk rule: the tail is capped at -1R (30 trades lost more than -1R before, none after), at the cost of 43 more trades, 60 more 10%-basis stop-outs and a lower win rate (48% to 43%, PF 2.96 to 2.66).
- B at 1%: about +4R realized (266.7 vs 262.5, interval +0.5 to +8.1), positive in both halves (+2.7R, +1.5R); the 46 zero-R entry-basis exits become small wins; 25 trades near break-even that survived are stopped out by the buffered stop (sum +3.1R to +2.2R).
- Together (A + B 1% + C 1.0): 488 trades, +266.9R realized, PF 2.64, 395 realized trades. The live rows moved: 52 of 117 (39 on stop, 7 on basis, 7 on status, 21 on entry); active to breached AME, AVGO, CAT, DDOG, META, NVDA; breached to active KLAC.

**Gray Down basis what-if (2026-10-19, report only; the what-if assumed free re-entries).** Gray Down keeps switching the stop to entry basis (no trailing afterwards). Two alternatives were measured against the live rules and rejected: **D1** (an LP-basis stop keeps trailing after a Gray Down floor) realized -2.2R (95% interval -15.8 to +10.6), differing on 14 baseline trades (4 exit higher, 7 lower or sooner), mixed across halves (-5.9R first, +3.6R second), 6 tickers up and 7 down; **D2** (10%-basis stops also trail) realized -2.4R (interval -53.4 to +34.0), 81 trades differ, -26.4R first half and +24.0R second half, worst single loss ARM -18.5R, the lowest profit factor, and it removes the -1R tail cap of rule A. Only 8 of the 59 baseline entry-basis exits came from LP-basis stops; 51 came from 10%-basis stops. Do not re-test unless the rules or the sample change materially (docs/decisions.md 2026-10-19).

**Applying a rules change (runbook note).** The stateless nightly replay rewrites every row whose result differs from the stored one, so a rules change is applied by the next nightly run on its own, with no seed or rebuild. The 2026-10-19 change was applied by hand instead, once, in this order: tests and an in-process acceptance replay of all 117 rows (nothing written); commit on main; a JSON export of `warrenwatchrow` and `warrenwatchcursor` to `/home/shen/backups`; then ONE call of the nightly step's own function, `update_watch_table(tickers, bars_by_ticker)` (`pipeline/nightly_warren_signal_calculation.py`), with the bars read from the shared cache (no network) and outside 01:05-02:30 UTC. Not the seed script, not `rebuild_warren_watch` (its guard replays `PREVIOUS_RULES` = the rules before this change, which no longer reproduces rows after the apply), not the event reconcile. Restore, if ever needed: stop the app and cron windows, then write the export's rows back into the two tables (the export holds every column of every row, removed rows included).

## Instruction texts on the Technical Ideas table (2026-10-19)

**Display only, derived at read time, nothing stored.** `instruction_type` and the stored `instruction_text` are written by the nightly exactly as before (the stored text is the chart's wording, `instructions.text_for`, and is no longer what the page shows). `data/warren_watch_data.py::watch_table` returns `instruction_text` from `analysis/warren_signal/watch_text.py::watch_instruction_text(profile, instruction_type, latest_arrow_at, entry_kind, entry_at, stop_moved_at, stop_moved_by)`. The chart's texts (`GENERIC_TEXTS`, `PROFILED_TEXTS`, "STOP HIT = EXIT OR RESET") are not touched. Because the type is read from the row, a stored text that was stale against its type (a row written before the 2026-10-17 text fix) now reads correctly too.

**Generic set** (every ticker except SPY/QQQ/TQQQ/TECL; the text says what the row did):

| Situation | Text |
|---|---|
| Yellow Up, new entry (no row, or after a stop-out) | YELLOW UP - New entry. Stop set 10% below the candle low. |
| Yellow Up, repeat, stop raised | YELLOW UP (repeat) - Stop raised. |
| Yellow Up, repeat, stop unchanged | YELLOW UP (repeat) - Stop unchanged, the new level is not higher. |
| First Yellow Up within 20 candles of a Blue entry (type 4) | FIRST YELLOW UP AFTER BLUE ENTRY - No action. |
| Blue Up, new entry (type 2) | BLUE UP - New entry, no stop. |
| Blue Up on an open trade (type 5) | BLUE UP - No change to the open trade. |
| Gray Up, new entry | GRAY UP - New entry (stopped out twice before, SPECULATIVE). Stop 10% below the candle low. |
| Gray Up on an open trade | GRAY UP - No change to the open trade. |
| Blue Down | BLUE DOWN - Stop raised to the LP support. / BLUE DOWN - Stop unchanged. |
| Yellow Down | YELLOW DOWN - Stop raised to the LP support. / YELLOW DOWN - Stop unchanged. / YELLOW DOWN - No action (blue entry). |
| Gray Down | GRAY DOWN - Stop raised to entry + 1%. / GRAY DOWN - Stop unchanged. / GRAY DOWN - No action (blue entry). |
| Breached row (drawn by the frontend, every profile; `STOP_HIT_TEXT`) | STOP HIT - Out of the trade until the next Yellow, Blue or Gray Up. (with "since <breach candle> ET" beneath; the tooltip carries "Last instruction: <the row's text>") |

The "1%" is built from `GRAY_DOWN_ENTRY_BUFFER` (`watch_text._BUFFER_PCT`), not a second copy.

**Derivation, from stored fields only.** *New entry* = `entry_at == latest_arrow_at` (every fresh entry stamps its own candle). *Stop raised* = `stop_moved_at == latest_arrow_at` AND `stop_moved_by` is the arrow's own mover (repeat Yellow: `yellow_up_repeat`, which is also what a repeat Yellow stamps on a blue entry's first stop; `yellow_up_entry` marks only a fresh yellow entry and is accepted by the code defensively, never stamped by a repeat Yellow; Blue Down: `blue_down`; Yellow Down: `yellow_down`; Gray Down: `gray_down`); otherwise unchanged. A trail on the arrow's candle stamps `trail`, so an arrow that did not move the stop reads "unchanged" (correct), and a trail on a later candle does too. Yellow Down and Gray Down on a blue entry read "No action (blue entry)" whatever the stop did. A Gray Up or Blue Up that is not the entry candle reads "No change to the open trade". Types 4 and 5 are fixed texts.

**Profiled set** (SPY, QQQ, TQQQ, TECL): their own short, arrow-type-only wording (`watch_text.PROFILED_WATCH_TEXTS`, no raised/unchanged variants), with two corrections: Gray Down "stop to entry" -> "stop to entry + 1%", and the repeat Yellow Up keeps "whichever is lower" for the candidate and adds "; the stop is never lowered below the current stop". Every other profiled string, and type 5, is verbatim. The chart still shows the unchanged profiled strings.

**Limits.** (0) "YELLOW UP (repeat) - First stop set.", in the decided text table of 2026-10-19, is never produced: a blue entry's first stop and a later raise are indistinguishable in the stored fields (both stamp `yellow_up_repeat` on the arrow's candle and the old stop is not stored), so both read "Stop raised". (1) A blue entry's FIRST stop and a later raise look identical (a repeat Yellow stamps `yellow_up_repeat` on the arrow's candle either way and the old stop is not stored), so both read "Stop raised"; the decided "YELLOW UP (repeat) - First stop set." is therefore never produced (no storage was added). (2) (rare, accepted) If an up arrow and a down arrow share a candle (one stamp, the down's is the latest arrow) and the up arrow moved the stop, the down arrow's text reads "unchanged". (3) The Blue Down / Yellow Down generic texts read "Stop raised to the LP support" (changed from "the 2nd LP" on 2026-10-19) because the ATR gate can walk the selected LP down to the 3rd support; the profiled set keeps "stop to 2nd LP" on purpose (it follows the ThinkScript labels). On 2026-10-19 all 3 live rows showing a raised Blue/Yellow Down text (ABNB, PAYX, MAR) sat on the 2nd LP, none on the 3rd. (4) Profiled strings still loose: Blue Down / Yellow Down "stop to 2nd LP" (raise-only, no-op when not higher) and Gray Up "NO ACTION ... stay out until BLUE UP" (a Gray Up with no open trade now opens a gray entry); left as written. (5) A legacy row with no entry on a Gray Up reads the chart's text.

## Removal

`remove_watch_row(ticker)` sets `removed_at` (naive America/New_York wall clock); the row stays (a soft delete; `DELETE
/api/technical-ideas/warren/{ticker}` calls it, phase 2).
From then on the ticker's candles at or before `removed_at` are not read (an arrow on a candle that started at or before the
removal is ignored even if it completes later), a removed row is not breached or refreshed, and only an up arrow on a later
candle wakes it: it becomes a fresh row (the old state is not carried over, `removed_at` cleared, `replay_from` = the removal time so the next replays do not bring the old trade back). `list_watch_rows` hides
removed rows by default.

## Nightly step

Final step of `pipeline.nightly_warren_signal_calculation` (1:25 AM), after the Warren replay, sweep and prune, reusing the bars
the job already read: `update_watch_table(tickers, bars_by_ticker)` calls `update_warren_watch` per ticker (the stateless replay above). No new cron entry: the `JOB_METADATA` description of the Warren job now says so, and a separate job was not
needed because the step needs the same 60m cache read and must see the same session. Failures are counted on their own
(`watch_failed`), never change the Warren results, and appear in the heartbeat message
(`...; watch table: N created, M changed, F failed`); `check_failure_threshold` applies to the watch step on its own counts.
"Changed" now includes rows corrected after a bars revision. The LP settings are read once per run. **The first run on the new code rewrites every row whose stored value differs from a fresh replay** (see "first run"); it was done by hand on 2026-10-17 (see "applied once by hand"), so the cron found nothing left to change.

**LP gate in the nightly step (2026-10-18).** The step also needs the ticker's cached **daily** bars for the ATR. `update_warren_watch` reads them per ticker with `read_cached_completed_daily_bars` (a pure cache read: no FMP call, no top-up, no write; it already drops a live or provisional newest bar), once per ticker before the row session opens, about 960 sessions (`DAILY_ATR_LOOKBACK_DAYS` = 1400 days). The same code runs from all three entry points: the nightly step and `pipeline.seed_warren_watch` (dry or for real) go through `update_watch_table` -> `update_warren_watch`; `pipeline/backfills/rebuild_warren_watch.py::replay_state` builds the same lookup (daily bars loaded once per ticker). The step logs one extra line, `Warren watch LP gate: N selections, ... with no daily ATR (gate off) ... Tickers with no daily ATR: K (...)`, and returns `watch_lp_gate` / `watch_no_daily_atr` in the summary. **Runtime (estimated from the code, not run):** the daily reads add roughly 136 small SQLite reads (a few seconds); the extra cost is LP computations, because a gated stop stays an `LP` stop longer and so trails on more candles (the what-if's trail requests rose by about half), about +50% LP calls on the 7,900 (about 120 s) a night: **the watch step about 120 s -> 180 s, the Warren job about 265 s -> 330 s**; it still ends around 01:31, before the 01:35 job.

## Registry

Both tables are `KEEP` in `data/ticker_data_registry.py`: the wipe never deletes them. The cursor is kept with its row (it carries the page's "as of"); since the stateless replay a wiped cursor no longer
re-applies anything.

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
- **Stops could move down, by one rule only (until 2026-10-19).** A second (armed) Yellow's `min(2nd LP, 0.9 x low)` could be below the first Yellow's stop; 349 of 442 repeat Yellows (79%) did on the 2026-10-19 data, and 30 trades lost more than -1R. Since 2026-10-19 no rule lowers a stop.
- **A Blue entry gets its first stop from a later down arrow.** PAYX: blue entry 101.80, Blue Down moved the stop to an LP at 101.42.
  Blue entries otherwise carry no stop and cannot breach.
- **A Gray Up on a breached row** used to advance `last_signal_at` (WDC: the Gray of 2026-10-15 re-dated a row whose trade began 2026-09-16 and was stopped on 10-13), then (2026-10-16) froze it; since 2026-10-17 it restarts the row as a gray entry (rule 2; WDC would show a gray entry at the 2026-10-15 15:30 close).
- **Gray-born rows** (IDXX, MTD in the first seed; superseded: the second rebuild gave both a yellow entry and a Gray Up now opens a gray entry, so no new row is born without an entry; the "No entry" badge stays in the UI for a legacy row). Originally they had no entry and no stop and the page showed them as "No entry", not "Active". IDXX's yellow trade pre-dates the 3-month
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
- A down arrow on a breached row is ignored (2026-10-17; it used to update the text only), so a breached row's arrow pill and sort position stay on the arrow that was last applied to it.

## Phase 2: API, page, nav

### API (`core/main.py`, schemas `WarrenWatchOut` / `WarrenWatchRowOut`, data `data/warren_watch_data.py::watch_table`)

| Route | Role | What |
| --- | --- | --- |
| `GET /api/technical-ideas/warren` | viewer | Every non-removed `WarrenWatchRow` plus `as_of`. Reads the stored tables only: no FMP call, no write, no `TickerView` touch (`tests/test_viewer_rules.py` runs it with the other viewer GETs). Also `anchor_headroom` (2026-10-18): the re-anchor banner data, filled only for an admin and only while the headroom is under 300 days, otherwise `null` (see "Anchor headroom and re-anchor runbook"). |
| `DELETE /api/technical-ideas/warren/{ticker}` | admin | `remove_watch_row`: sets `removed_at`. 404 when the ticker has no row or it is already removed; 422 for a malformed symbol (it carries `TickerPath`, as the registry test requires). |

Both are registered in `core/route_roles.py`. The route lives under `technical-ideas`, not `tickers/{ticker}`, because it is a
page-level table, not a ticker resource (a viewer is not restricted to tracked tickers here: the table is already the monitored set).

**`as_of`** is the newest `WarrenWatchCursor.processed_through` (the last completed 2h candle any ticker was folded through; it
covers tickers with no row), falling back to the rows' own `as_of`; `null` only before the first seed.

**Row fields:** `ticker`, `profile`, `latest_arrow_color` (`blue`/`yellow`/`gray`) and `latest_arrow_direction` (`up`/`down`) split from the
stored kind, `latest_arrow_at`, `instruction_type`, `instruction_text`, `entry_kind` (`blue`/`yellow`/`gray`), `entry_price`, `stop_price`, `stop_basis`, `status`,
`breached_at`, `last_signal_at`, `last_updated_at`, `age_bars`, `last_signal_age_bars`, and (2026-10-16) `entry_at`, `last_price`, `last_price_date`, `pl_pct`, `stop_distance_pct` (next paragraph), `stop_moved_at` (naive ET) and `stop_moved_by` (null on a row with no stop age), and (2026-10-18) `stop_trailed_since_arrow` (boolean, display only, derived in `watch.py::stop_trailed_since_arrow` from `status`, `stop_price`, `stop_basis`, `stop_moved_by`, `stop_moved_at` and `latest_arrow_at`; both stamps are candle window starts from the same 2h index, so they compare directly; false whenever the row is breached, has no stop or no stop age, or the basis is not `LP`). `removed_at` is not returned.

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

Table (`WarrenWatchTable`, modelled on `MomentumTable`: kit Table, compact Badge pills, mono tabular numbers, no row click (since
2026-10-18): only the ticker link opens `/tickers/{t}`, in a new tab, and the row has no pointer or hover styling; the Remove control keeps its own click):

| Column | Content |
| --- | --- |
| Ticker | Link; a profiled ticker (spy/qqq/tqqq/tecl) shows "<profile> profile" beneath. |
| Signal | Up/down pill in the arrow's colour: Blue = `chart-ema21` (the chart's own blue for Blue arrows), Yellow = `chart-warren-yellow`, Gray = `chart-warren-gray`. Title: the arrow candle's time. A row whose trade was opened by a Gray Up (`entry_kind = gray`, 2026-10-17) also shows a small neutral **"Gray entry"** tag under the pill, tooltip "Two stop-outs in a row, higher risk" (`GRAY_ENTRY_NOTE`). |
| Instruction | The derived text ("Instruction texts on the Technical Ideas table"), wrapped to at most 2 lines, truncated beyond that, the full text in the tooltip (the longest string is the profiled Yellow Up, about 165 characters; the generic set tops out near 95). **A breached row** shows **"STOP HIT - Out of the trade until the next Yellow, Blue or Gray Up."** with "since <breach candle, ET>" beneath instead (display only: the stored instruction type, text and stop are unchanged; the tooltip carries "Last instruction: <the row's text>"). |
| Entry | `entry_price`, mono, dash with no entry (Gray-born rows). Tooltip: entry kind (Blue/Yellow/Gray), the entry candle's ET stamp (`entry_at`), its age ("7 months ago", `fmtAgeAgo`) and "The close of the entry candle, not an actual fill." |
| Last | `last_price`, the latest daily close; tooltip "Daily close of <last_price_date>"; dash when null. |
| P/L % | `pl_pct`, signed, one decimal (`fmtSignedPct1`). **Active row:** `(last_price - entry_price) / entry_price`, green above the entry, red below. **Breached row (2026-10-16): frozen at the stop**, `(stop_price - entry_price) / entry_price`, computed server-side (`data/warren_watch_data.py::row_pl_pct`) from stored fields, so it does not move with the daily close; an estimate of the exit, not a fill (a gap through the stop is not included). Neutral colour (no green/red) with the tooltip "Stopped out at $<stop> on <breach date> ET. P/L estimated at the stop, not a real fill; gaps through the stop are not included." (`breachedPlTitle`). A new Yellow/Blue Up that returns the row to active switches it back to the active formula by itself. Dash with no entry, or on a breached row with no stop. Last and Stop dist. keep following the cached daily close, so on a breached row Stop dist. is how far price has moved from the stop since the stop-out. |
| Stop | Price plus a neutral basis tag (`10%`, `LP`, `Entry`); the `LP` tag is **yellow** (the `warn` pill tone; title and aria-label "LP, trailed since last arrow") when `stop_trailed_since_arrow` is true, and the cell tooltip then gets a second line: "Trailed since last arrow: the stop was moved by the trailing LP (not by an arrow) at <time> ET, and stays highlighted until the next arrow." (`lib/technicalIdeas.ts::showTrailedPill` / `stopCellTitle`); a dash when there is no stop. A stop above the entry price shows normally with a small info icon whose tooltip says the latest instruction set it (2nd LP / entry price), so it does not read as a bug. **Stop-age tooltip** on the cell (`stopAgeTitle`): "Set at entry, Jun 11, 09:30 ET (10% of the candle low)", "Repeat yellow, Aug 3, 11:30 ET (lower of 2nd LP and 10%)", "Set Oct 15, 11:30 ET by Blue Down (2nd LP)" / "...by Yellow Down (2nd LP)", "Gray Down: stop set to entry, Sep 23, 13:30 ET", "Set at entry, ... (10% of the candle low, gray entry)" (`gray_up_entry`), "Trailed to 2nd LP Oct 16, 13:30 ET", each followed by " · <age>" (`fmtAgeAgo`); no line when `stop_moved_at` is null. |
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

Top-level links are Stocks, ETFs, Watchlist; then two dropdowns (the Markets pattern, one `NavMenu` component):
**Investing** (Technical Ideas, Weekly Routine, Momentum; order since 2026-10-18) and **Markets** (Sectors, Breadth). Weekly Routine is the
label of the former Opportunities page (URL `/opportunities` unchanged); Momentum left the top level. `/technical-ideas` is a same-tab page like
`/opportunities`. Investing is marked current on any of its three routes.

### Open for a later phase

- **Review the instruction text: done 2026-10-19**, see "Instruction texts on the Technical Ideas table".
- **Intraday refresh.** The table is as of the last nightly run; a refresh during the session would need the 60m cache topped up and the step
  run outside the Warren job (the replay is stateless, so re-running it is safe; the cursor is bookkeeping only since 2026-10-17), plus a decision on whether a forming candle may ever breach a stop.
- **A second strategy section** needs only a new section component and hook; the page and the shell do not change.
- **RMD / ADP / ROBO / stored-row drift (2026-10-17). FIXED the same day by the stateless nightly replay (see "Stateless nightly replay" and "first run"); the finding is kept for the evidence.** 14 rows do not equal a replay on today's cache (ADP, ALAB, ASML, CRWV, LITE, MPWR, MU, QQQ, RMD, ROBO, SNPS, STX, TQQQ, VRT), so the rebuild's guard skips them.
  **Cause: the nightly watch step folds a session's candles in the night right after it, from FMP 60m bars that are still provisional, and the cursor then never looks at those candles again.**
  Evidence: `SharedBarsCache.fetched_at` shows the last ~5 sessions re-fetched every night (the 10-12 to 10-16 bars were all rewritten on 10-17 01:20); the newest session's bars still carry raw prices (ADP 10-16 13:30 close 285.7792, RMD 12:30 238.345 and 15:30 238.965) where older bars are 2-decimal; 12 of the 14 rows were created or moved on the 10-15 session and differ from the replay by cents (ALAB entry stored 294.6434 vs 294.59 now); `WarrenSignalEvent` rows are append-only and
  carry arrows today's replay no longer produces (ADP: gray_down and yellow_down 10-09 15:30, yellow_down 10-15 12:30 stamps) or got an arrow only a night late (RMD: gray_down 10-15 15:30 inserted 10-17 01:26, not 10-16). The replay itself is causal and stable (identical arrows through 10-15 15:30 or 10-16 15:30, and with the bar history's start moved by 1 to 90 days), so the difference is the bars; some arrows are knife-edge (RMD's gray_down at 10-15 15:30 moves to 10-16 09:30 when that bar's close changes by +0.05%).
  The older bars are overwritten, so the exact provisional values could not be re-read; the 10-16 03:30 nightly backup holds them (not unpacked: it needs about 1.4 GB of scratch on a disk with 1.5 GB free).
  **Which side is right:** the replay on the final bars. **RMD:** stored = yellow entry 219.74 (2026-09-09 13:30), 10% stop 196.87, arrow yellow up; replay = the 10-15 15:30 Gray Down is real. **ADP:** stored = blue entry 211.67, 10% stop 240.07 (yellow up repeat 09-11), arrow yellow down 10-15; replay = blue down 10-15 11:30 only (no yellow down), 2nd-LP stop 263.90 trailed 10-16 11:30; a 24-point stop difference, ADP is active either way (last close 288.95).
  **RMD rebuilt under the current rules would NOT be a yellow row:** the replay finds a Gray Up on 2026-06-03 15:30 on a row with no open trade, so the entry is gray at 186.52 and the 09-09 Yellow is only a repeat Yellow (stop, not entry, by the gray-entry rule); the 10-15 Gray Down then puts the stop at the entry price 186.52 (entry below the close); active, arrow gray down. (With the previous rules and the same bars it is yellow 219.74, stop 219.74 entry-basis.) This is the rules working as specified, but a long-lived gray entry can sit months under later yellow signals: review before applying RMD.
  **Not a bug in the rebuild** (its guard did its job). It is a design weakness of the cursor: every row that was created or moved by the most recent session is exposed (33 rows have an entry, stop, breach or arrow stamp on 10-15 or 10-16; the 10-16 candles were processed on 10-17 01:27 from the not-yet-final bars), and the next night's refetch can make any of them differ. ROBO also differs (its stored row starts at the 10-15 15:30 Yellow while its events show Yellow Ups from 08-21; not investigated, cause unverified).
  **Recommended fix (built 2026-10-17, commit with this spec):** make the nightly step stateless: replay every row from `REBUILD_START` on the current cache each night and write the rows that differ (about 40 s and 2.6k LP calls for 117 rows, the rebuild without the guard replays), or at least rewind the cursor by the re-fetch window (about 5 sessions) and replay from a stored state. Until then, rerun the dry rebuild after a rule change and expect the newest session's rows to be skipped.
- **Stale `WarrenSignalEvent` rows (2026-10-17). FIXED 2026-10-18: the event log is reconciled with the replay every night and the one-time cleanup was applied (see "Event log reconcile").** The events table kept arrows computed on provisional bars or on the previous bar source, because events were insert-only.
- **Anchor (deadlines verified 2026-10-18, headroom 361 days).** `REPLAY_ANCHOR` is a fixed date and the nightly slice's start moves forward one day a day, so the headroom (anchor minus the slice's first date) falls one day a day: **warning from 2026-12-19** (under 300 days; the admin banner appears), **urgent from 2027-01-18** (under 270; arrows start flipping in the sliding-start test), **hard deadline 2027-04-17** (180 days, the event write gate's warm-up). **Set a calendar reminder for early December 2026** (for example 2026-12-07), and re-anchor in the week of 2026-12-21 following "Re-anchor runbook" below. The banner computes the dates live, so they move only if `REPLAY_ANCHOR` or `LOOKBACK_DAYS` is changed.
- **LP gate trial (2026-10-18, open).** Adopted on main as a trial without a dry run; re-measure after a down or sideways stretch (the what-if year was mostly rising, the gain sat in the first half). Things to watch: rows that were breached and reopen (status flips), `LP`-stop trades held longer, the share of gate rejections in the nightly log line, tickers with no daily ATR. See "LP gate" below.
- **Warren job runtime** grew from about 150 s to about 280 s (LP calls). If it threatens the 1:35 job, memoise the 2nd LP per (ticker, candle) or move the anchor.
- **Gray entries are new (2026-10-17).** The gray rules have no live history: check the first real Gray Up entry end to end (entry at the close, 10% stop under the low, tag, tooltip), and watch whether a gray entry that is later hit by a Blue Up behaves as wanted (rule 2: it keeps the entry and the stop; the Blue is only shown in the pill and instruction).
- **Ignored down arrows on a breached row** hide the newest arrow: a breached row's "Last signal" can now be weeks old while a down arrow fired yesterday. Revisit if that reads as stale.
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

## Fourth rebuild: gray entry and breached-row rules (2026-10-17, applied)

Rule changes (watch.py, `WatchRules`): a Gray Up with no open trade opens a gray entry; every up arrow restarts a breached row; down arrows are ignored on a breached row; a
Blue Up never replaces an active gray entry. `pipeline.backfills.rebuild_warren_watch` was updated for it:

- Replays every non-removed row from `REBUILD_START` through its cursor with the CURRENT rules, the cached 60m bars (no FMP call) and today's LP settings, and diffs all fourteen fields.
- **Mismatch guard:** a differing row is rebuilt only if the same bars and LP settings replayed under `PREVIOUS_RULES` (no gray entry, down arrows applied on a breached row, Gray Up frozen on a
  breached row; trailing ON) reproduce the stored row on all fourteen fields. A skipped row prints what the rule change alone would do to it (`old` replay vs new replay on today's bars).
- Prints the new flip counts: breached -> active, no entry -> entry, rows now on a gray entry, rows whose arrow fields change and how many of those only because breached-row down arrows are now
  ignored (an extra replay under the current rules with those arrows applied), and the rows still without an entry. Dry run by default; `--apply` is unchanged (only the differing rows, never
  `removed_at`, the cursor, `as_of` or `last_updated_at`).

Dry run on the real database (117 non-removed rows, cursors at 2026-10-16 15:30; 132 s, 7843 LP calls): **95 identical, 8 changing, 14 skipped by the guard**.
- Flips: active -> breached 0; breached -> active 2 (IDXX, WDC); no entry -> entry 0 (no stored row lacks an entry; the "No entry" badge shows on no row).
- Rows now on a gray entry: 3, all restarts of a breached row by a later Gray Up (IDXX 2026-09-11 15:30, MTD 2026-09-11 11:30, WDC 2026-10-15 15:30).
- Arrow/sort fields change on 6 rows; 5 of them only because down arrows on a breached row are now ignored (CIBR, FIX, IGV, LMT, NTAP: the pill reverts to an older arrow; LMT 10-16 15:30
  Blue Down -> 09-08 Yellow Up, FIX 10-06 -> 08-26, NTAP 10-02 -> 08-25, CIBR 09-15 -> 08-27, IGV 08-27 -> 08-04), the sixth is WDC's restart.
- Named rows: IDXX breached -> active gray entry 504.88 (2026-09-11 15:30), stop moved to entry 504.88 by the 10-16 Gray Down (entry below the close); MTD gray entry 1300.04, stop trailed to 1485.02 LP
  (above the entry) and breached 2026-10-01; WDC gray entry 356.43 (2026-10-15 15:30), stop 315.68, active. QCOM, LRCX, MRNA unchanged (QCOM yellow 149.69 active; LRCX and MRNA stay breached with their
  entries; MRNA's frozen P/L is unaffected). The 2 rows with no stop, DASH and SYK, are blue entries (a Blue sets no stop) and are unchanged.
- 14 skipped: 11 are cent-level drift between the stored entry/stop and today's cached bars (ALAB, ASML, CRWV, LITE, MPWR, MU, QQQ, SNPS, STX, TQQQ, VRT; the rule change alone changes none of them);
  ADP differs in its arrow history (also unchanged by the rules); **RMD and ROBO differ for other reasons and RMD would be a gray-entry row under the new rules** (RMD stored yellow 09-09 vs a replay
  that ends on a Gray Down 10-15; ROBO is a row created by the nightly job after the third rebuild, with a different window start). They stay as stored until reviewed.

**Applied 2026-10-17** (owner approval) after a verified backup, **8 rows written**: IDXX, MTD, WDC (gray entries), CIBR, FIX, IGV, LMT, NTAP (arrow/instruction reverted to the last arrow applied before the breach). The dry run just before the apply gave exactly the same 8 rows. A before/after dump of both tables showed exactly those 8 rows changed; `removed_at`, `as_of`, `last_updated_at` and all 136 cursors were identical on every row. A rerun reports 117 non-removed rows, 103 identical, **0 changing**, 14 skipped (the same 14).
- **Backup:** `/home/shen/fathom/backend/fathom_pre_rebuild4_20261017_083559.db` (SQLite online backup, 1,408,663,552 bytes = the original's size, same page count and `warrenwatchrow` / cursor row counts, `quick_check` ok; kept on purpose, git-ignored by `*.db`). It is 1.4 GB on a disk with about 1.5 GB free: delete it once the rebuild has been checked in use.
- Before/after (entry, kind, stop, basis, status): IDXX 637.14 yellow, 513.88 10%, breached -> 504.88 gray, 504.88 entry, active (P/L -19.3% -> +11.0%); MTD 1237.81 yellow, 1070.24 10%, breached -> 1300.04 gray, 1485.02 LP, breached 2026-10-01 (P/L -13.5% -> +14.2%, frozen at the stop); WDC 425.00 yellow, 376.25 10%, breached -> 356.43 gray, 315.68 10%, active (P/L -11.5% -> -6.9%, instruction "GRAY UP - NO ACTION"). The five down-arrow rows keep entry, stop and status: CIBR pill yellow down 09-15 -> gray down 08-27, FIX blue down 10-06 -> yellow up 08-26, IGV yellow down 08-27 -> blue down 08-04, LMT blue down 10-16 -> yellow up 09-08, NTAP blue down 10-02 -> yellow up 08-25.
- The 14 skipped rows were left alone (see "RMD / ADP / stored-row drift" in the open items).

## Gray Down raise-only: effect on stored rows (2026-10-17, dry run only, NOT applied)

Dry run of `pipeline.backfills.rebuild_warren_watch` under the raise-only rule on the real database (117 non-removed rows; 153 s, 9284 LP calls): **93 identical, 10 changing, 14 skipped by the guard** (the same 14).
All 10 changing rows trace to a stop that the old rule lowered to the entry price: it then breached, or did not breach, at a different candle, and the next Yellow Up restarted the row (8 entry changes).
- A: active -> breached 2026-10-01 11:30; stop 111.69 entry -> 169.60 LP (trail 09-29), moved by trail.
- APH: breached -> active; entry 62.52 (05-12) -> 77.47 (08-21), stop 77.985 LP -> 69.219 10%.
- COST: stop 903.65 entry -> 953.63 LP (trail 10-16).
- LRCX: entry 290.73 (09-03) -> 301.13 (10-13 15:30), stop 265.70 LP -> 268.43 10%, breached_at 10-16 13:30 -> 10-15 09:30.
- Entry only (stop and status unchanged): FTNT 78.98 -> 151.51 (08-21), KEYS 199.82 -> 316.75 (08-20), PLTR 112.69 -> 169.46 (09-02), RY 159.23 -> 205.83 (08-24), SOXX 318.33 -> 541.16 (10-13), UNH 273.9 -> 391.32 (08-21).
- Named: IDXX, WDC and MTD are unchanged (their Gray Downs did not lower a stop). **RMD** is skipped by the guard (provisional-bar drift) but its replay under the new rule is a yellow entry 219.74 (09-09 13:30) with stop 219.74 (entry basis, raised by the 10-15 Gray Down), active, instead of the gray 186.52 trace: the 07-06 Gray Down no longer lowers the LP stop 192.84, so the June gray entry is breached before 09-09 and the Yellow restarts the row.

## Stateless nightly replay: first run, events and consumers (2026-10-17)

**What the first nightly run on this code writes** (dry run of `seed_warren_watch --dry-run` on the live cache, 136 tickers, 0 created, **24 rows would change**, 0 failed, 8,123 LP calls, 127 s; nothing was written and the schema was not touched):
- **Gray Down raise-only (11 rows):** A (active -> breached 10-01, stop 111.69 entry -> 169.60 LP), APH (breached -> active, entry 62.52 -> 77.47), COST (stop 903.65 -> 953.63 LP), LRCX (entry 290.73 -> 301.13, breached 10-16 -> 10-15), MU (entry 847.38 on 07-30 -> 952.43 on 10-13), FTNT, KEYS, PLTR, RY, SOXX, UNH (entry only; each entry moves to a later Yellow Up).
- **Provisional-bar drift (10 rows, cents):** ALAB, ASML, CRWV, LITE, MPWR, QQQ, SNPS, STX, TQQQ, VRT (entry or stop prices from the 10-15 session's not-yet-final bars; ALAB 294.6434 -> 294.59).
- **Arrow history revised (3 rows):** ADP (the 10-15 yellow_down is gone: blue_down, stop 240.07 10% -> 263.90 LP trailed 10-16), RMD (the 10-15 15:30 gray_down appears: yellow entry 219.74 stays, stop 196.87 -> 219.74 entry basis, active), ROBO (the 10-15 15:30 yellow_up was a provisional-bar arrow and is gone: yellow entry 81.18 on 08-21, LP stop 80.27, **breached 2026-10-08**, instead of an active fresh entry 77.33).
IDXX, WDC, MTD, CIBR, FIX, IGV, LMT and NTAP (the fourth rebuild's 8 rows) do not change. The rebuild script's own dry run under the same rules reports 117 rows, 93 identical, 10 changing, 14 skipped by its guard (the guard cannot vouch for stored rows that differ for other reasons than a rule change; the nightly step has no guard by design); for RMD, ADP and ROBO the rebuild's replay and the new step's are identical and each is identical on a second replay.

**`WarrenSignalEvent` is untouched by the watch step** (as of 2026-10-17 it was append-only; the 2026-10-18 reconcile branch ends that, see "Event log reconcile"). Stale events therefore still exist on main (ADP's 10-09 gray_down and yellow_down, 10-15 yellow_down; ROBO's 10-15 yellow_up), and the new step does not stop new ones: it changes what the watch table says, not what the events table records. Who reads events: the Chart tab's markers on the daily ranges (`data/chart_data.py::_fetch_warren_signal_events`: a stale arrow shows as a marker there), the Opportunities daily flags (`opportunity_daily_data._load_events`: stale UP arrows count as triggers), and `TickerScore.warren_last_buy_fired_at` (`last_buy_signal_fired_at`). **The Technical Ideas page and its API read only `WarrenWatchRow`/`WarrenWatchCursor`, never the events, so the page no longer shows stale arrows after a rewrite. There are no alerts built on events.** A stale UP event can still feed an Opportunities trigger or the screener's last buy date (open item).

## Stateless nightly replay: applied once by hand (2026-10-17, owner approval)

The first run of the stateless step was done by hand on 2026-10-17 (about 12:20 UTC) instead of waiting for the 1:25 AM cron, so the 24 expected rows changed under supervision. Same step, same cached bars, no download (sockets blocked): `init_db()` first (it added `WarrenWatchRow.replay_from`), then `update_watch_table` over the 136 monitored tickers: **24 changed, 0 created, 0 failed**, 8,123 LP calls, 126 s.
- **Rows (exactly the 24 the dry run listed):** Gray Down raise-only A, APH, COST, LRCX, MU, FTNT, KEYS, PLTR, RY, SOXX, UNH; price drift ALAB, ASML, CRWV, LITE, MPWR, QQQ, SNPS, STX, TQQQ, VRT; arrow fixes ADP, RMD, ROBO.
- **Verified:** a before/after dump of `WarrenWatchRow` (117 rows), `WarrenWatchCursor` (136) and `WarrenSignalEvent` (3,337) showed only those 24 rows changed (and `last_updated_at` moved only on them); `removed_at` and the new `replay_from` (all null) untouched; the events table and every cursor identical. A dry run right after reports **0 changing**, so tonight's cron has nothing left to change.
- **API:** the endpoint needs a login (a viewer or admin session, none was created), so the running app was checked unauthenticated only (`/api/health` 200, the warren route 401 as designed) and the endpoint's own data function and response model were run in-process on the live DB: 117 rows (= the non-removed rows), as_of 2026-10-16 15:30, spot checks (FTNT, RMD, ROBO, IDXX, AAPL) equal to the stored rows. The running app was not restarted: it still runs the old code, which does not read `replay_from` and is unaffected by the new column.
- **Backup:** `/home/shen/fathom/backend/fathom_pre_stateless_20261017_121242.db` (SQLite online backup taken just before the apply; same size 1,408,663,552 bytes, same page count 343,912, `quick_check` ok, same row counts for the watch row, cursor and event tables). The earlier `fathom_pre_rebuild4_20261017_083559.db` was deleted to make room (disk 1.54 GB free with this one). Delete this one too once the result has been checked in use.
- **Revert plan:** stop the app and the cron jobs; restore the backup over `backend/fathom.db` (and remove `fathom.db-wal` / `fathom.db-shm`; this also drops the `replay_from` column, which is harmless to leave if only the rows are wanted back); then `git revert 1e43b3b 6797c38` (stateless step, then raise-only) so the nightly job does not rewrite the rows again.
- **Why the old trades ended (new rule), FTNT / UNH / MU:** the old rule let a Gray Down set an LP stop back to the (old, low) entry price, and an entry-basis stop never trails, so the old trade survived months it should not have. Raise-only keeps the LP stop and the trail continues. FTNT: yellow entry 78.98 (01-05); 05-07 Yellow Down LP 82.43, trailed to 127.47 by 05-26; **breach 05-27 09:30** (low 126.95); Yellow Up 08-21 09:30 restarts at 151.51 (the old 05-08 Gray Down had dropped the stop to 78.98 and it never breached). UNH: entry 273.90 (02-06); 04-07 LP 271.27, trail to 350.55 by 04-24 13:30 (the 04-10 Gray Down used to lower the 280.51 stop to 273.90); **breach 04-27 09:30** (low 348.95); Yellow Up 08-21 restarts at 391.32. MU: entry 847.38 (07-30); 09-22 Blue Down LP 917.71, trail to 1044.00 by 09-25 (the 09-23 Gray Down used to lower it to 847.38); **breach 09-28 09:30** (low 1032.00); Yellow Up 10-13 15:30 restarts at 952.43 (10% stop 845.56, repeat Yellow 10-15 to 829.11).

## Raise-only down arrows and Blue Up no-op (2026-10-17, branch `warren-raise-only-arrows`, dry run only, NOT merged, NOT applied)

**Rules** (see "Rules at a glance"): Blue Up on an open trade changes nothing about the trade (instruction type 5, "BLUE UP - no change to an open trade"; the first-Yellow-after-Blue
counter still resets); Blue Down and Yellow Down are `max(stop, 2nd LP)`; Gray Down was already raise-only; the armed repeat Yellow is the only rule that lowers a stop. No schema change
(`instruction_type` is an int, type 5 exists only in the watch table's text map). `PREVIOUS_RULES` replays main's rules; the rebuild guard replays `PREVIOUS_RULES`.

**Dry run on the live database** (cached bars, today's LP settings; nothing written): the rebuild script reports 117 non-removed rows, 111 identical, **6 changing**, 0 skipped by the guard; the nightly step
(`seed_warren_watch --dry-run`) reports 136 tickers, 0 created, **6 would change** (the same six), so tonight's cron would rewrite 6 rows if the branch were merged. The six: ADP (blue entry 211.67 @02-12 13:30 -> 209.15 @11:30), DASH (blue entry 197.86, no stop -> yellow
entry 154.72 @05-14, stop 154.72 `entry`, P/L -4.4% -> +22.3%), NOC (589.56 -> 589.72), PAYX (101.80 -> 101.51), PTC (116.23 -> 114.08), SNPS (yellow entry 468.14, stop 418.78 `10%` -> entry 376.96 @09-16, stop 403.30 `LP`, P/L -2.9% -> +20.6%).
Five come from the Blue Up switch (an earlier Blue Up now stays the entry), one (SNPS) from the raise-only down arrows. BKNG and SYK (blue rows), RMD, ROBO, IDXX, MTD, WDC, FTNT, UNH and MU do not change.

**Replay statistics** (equal-risk, the same definitions as the earlier reports; 136 tickers, 2025-10-15 15:30 to 2026-10-16): trades 483 -> 450 (the 34 trades "replaced by Blue Up" are gone: 0), breached non-blue 350 -> 353, total realized R +254.4 -> +243.5,
expectancy +0.727R -> +0.690R, median +0.09 -> 0.00, profit factor 3.00 -> 2.85, win rate 52% -> 48%, break-even exits 36 -> 45, R below -1: 23 -> 25; with unrealized R +259.8 -> +252.4 (-7.4R over 9 tickers whose last trade differs; 2 tickers better, 11 worse, sign test p = 0.02; bootstrap 95% CI of the mean change per ticker -0.116R to +0.003R).
Stops lowered at any point: only the repeat Yellow (138 trades; before 137 + Yellow Down 4 + Blue Down 6). Blue entries (no initial stop, % P/L only): 21 -> 18 counted, average +9.1% -> +11.1%.
Small and close to what the sample can resolve; the mechanism (a Blue Up in a trade no longer wipes the entry) is the change, not the number.


### Merged into main (2026-10-17, 23:38 UTC, fast-forward, not pushed)

Branch `warren-raise-only-arrows` (commits `6b5ca2b` raise-only down arrows / Blue Up no-op, `1f72648` instruction text follows the pill) was fast-forwarded into `main` (main was `b19cbc4`) and deployed by restarting the backend. The two commits plus this docs commit are the whole change; no schema change. **The full test suite is pending the owner's confirmation:** the new and updated tests were written but never run. No dry run was run for the text change, so the set of text-only rows tonight's replay will rewrite is unverified (the last dry run, before the text fix, expected 6: ADP, DASH, NOC, PAYX, PTC, SNPS).

**Revert plan.** `git revert 1f72648 6b5ca2b` (newest first) on main, restart the backend; the next nightly replay rewrites the rows back (it is stateless, so reverting the code is enough). Restore `backend/fathom_pre_stateless_20261017_121242.db` only if the data looks wrong, because it is older than the stateless replay and loses everything written since.

### Full test suite and backups (2026-10-18)

**Full backend suite on `main` at `3bcdaa8`** (run 00:02-00:23 UTC): **5996 passed, 2 failed**, 0 errors, 0 skipped, 1225.91 s. The two failures, both re-run alone and failing again, are not bugs in the new code:
- `tests/test_warren_watch_data.py::test_seed_replays_twelve_months_and_creates_rows_only_for_tickers_with_an_up_arrow_in_the_last_three`: **encodes the old rule, not yet updated.** Ticker NEW has a Yellow Up (2026-05-04) and a later Blue Up (2026-09-01); the test expects the Blue Up to replace the entry (`entry_kind == "blue"`), but a Blue Up in an open trade is now a no-op, so the row stays yellow.
- `tests/test_warren_watch_api.py::test_a_breached_rows_pl_is_frozen_at_the_stop_and_ignores_the_last_price`: **unrelated, weekday-dependent.** `add_daily_bars` dates bars `days_ago` before today; the test adds a bar 1 day ago, which on a Sunday is a Saturday, after the last completed session, so `read_cached_completed_daily_bars` drops it (last price 60.0, expected 150.0). It passes on a weekday run.
Neither was changed or skipped; both are open items for the owner.

**Production check.** The 01:25 UTC Warren job on 2026-10-18 ran the merged code: 136 tickers, 0 created, **6 changed**, 0 failed (the six rows the dry run expected; no extra text-only rows).

**Backups.** No `fathom_pre_*.db` other than the keeper existed (`fathom_pre_rebuild4_20261017_083559.db` had already been deleted; only its empty `-shm` / `-wal` stubs remain, untouched). Nothing was deleted. `backend/fathom_pre_stateless_20261017_121242.db` (1,408,663,552 bytes, 2026-10-17 12:12 UTC) is retained as the restore point; the revert plan above is unchanged.

## Event log reconcile (2026-10-18, merged into main and applied once)

**What a phantom is.** A `WarrenSignalEvent` row at or after the write gate that today's replay of the same bars does not produce. Events used to be insert-only (`_upsert` wrote with `on_conflict_do_nothing`; the only delete was the age prune), so an arrow that later moved or vanished left its old row for good.

**Where events are written.** `data/warren_signal_data.py::_upsert`, called by `compute_and_store_warren_signal` for each ticker in `pipeline/nightly_warren_signal_calculation.py::main` (1:25 AM). The job replays the whole 730-day slice of cached 60m bars every night (the slice `get_or_fetch_bars_batch` hands it: `LOOKBACK_DAYS` calendar days ending today), so it recomputes every arrow every night, but it only INSERTED the ones at or after `first candle + 180 days` (the write gate, which slides forward a day each day). There is no cursor in the event path (`WarrenWatchCursor` belongs to the watch table and is bookkeeping only); an event is never revisited because the writer never compared the log with the replay.

**Why 141 phantoms (all 136 tickers, the nightly's own input and gate; 2,575 stored events at or after the gate, 2,434 reproduced, 0 missing).**
- By insert batch: the 2026-09-12 bulk write 116 of 1,267 (9.2%); nightly 09-13..09-25 (before the refetch) 18 of 145 (12%); the first night after the FMP refetch, 09-26, 0 of 149; nightly 09-27 onward 7 of 1,014 (0.7%).
- **Bar-source change (confirmed, 132 of 141: the 116 of the 09-12 bulk and 16 first-time history writes of 09-13..09-25).** All 60m history was re-fetched from FMP on 09-26 07:16 (the provenance trigger replaces Yahoo-era rows). The 09-12 events carry float32-noisy stops (437.72398681640624) and slightly different lows; 113 of the 116 are on candles more than 30 days old when written, so they are not provisional-bar cases. The 09-26 night inserted the arrows at their new candles; the old rows were never removed.
- **Provisional newest session (partly confirmed, 9 of 141: 2 before the refetch, 7 since).** All 7 phantoms written nightly since 09-27 (ADP 3, CRM, INTC, NTAP, ROBO) sit on the newest session of their night: 7 of 93 events written the night of their candle (7.5%) against 0 of 921 on older candles. Each candle's bars were rewritten after the event was created (ADP's 10-09 bars on 10-16, six nights later; INTC's 10-13 bars on 10-17), consistent with the documented rewrite of the last `INTRADAY_OVERLAP_DAYS` = 5 sessions. But 105 of 110 same-night events that ARE reproduced were also rewritten afterwards, and the old values are not retained, so a revised value cannot be shown directly.
- By shift (same type, nearest replay arrow): 57 no match at all; one candle away 38 (the replay's arrow is a candle earlier in 20, later in 18); two candles 10; three to five candles 18; 17 the same candle with the other kind (yellow/gray flip); 1 on a candle that no longer exists.
- By threshold margin on today's bars: 72 knife-edge (under 0.5 RSI points), 20 near (0.5-2), 5 clear (2 or more), 43 where the conditions hold today but the arrow does not fire (a latch or stop-count state differs after an earlier shift), 1 not applicable. META: blue_down 01-29 (RSI one candle earlier 80.742 against 80.81) and yellow_up 05-04 (RSI 29.78, needs above 30).
- **The 14 "missing" arrows and 22 of the 162 were a gate effect.** The earlier count (162 / 14) replayed all cached bars (gate 2025-03-18); the nightly replays only 730 days (gate about 2025-04-19). All 14 missing and 22 of the phantoms are dated before the nightly gate, where leading-edge replay is unreliable by design; on the nightly's own input there are 141 phantoms and 0 missing (one phantom, MPWR gray_down 2025-05-13, appears only on the shorter slice).

**The rule (as built).** Each night, per ticker, after the replay: take the stored events at or after the write gate; DELETE those the replay does not produce, INSERT replay arrows with no stored event (created_at = now), LEAVE matching events untouched (created_at and stop_price as written). Events before the gate are never read or changed. The stamp convention (the window's last bar), the unique key and every column are unchanged; no migration. Guards: a stored event after the last replayed candle is never deleted; a replay that yields no event at all for a window that holds events, or a reconcile that would delete 5 or more events and over half the window, is refused and logged (nothing written for that ticker); a ticker with no bars or a failed replay raises before any event is touched. Idempotent. Entry points: `reconcile_events` (data/warren_signal_data.py), `plan_warren_event_reconcile` (pure read), `apply_warren_event_reconcile`, `pipeline/backfills/reconcile_warren_events.py` (dry run by default, `--apply` for the one-time cleanup). The nightly summary gains `events_added`, `events_deleted`, `events_skipped`, `events_changed_tickers`, `score_rows_refreshed`; the heartbeat message gains "; events: N added, M deleted, K skipped" only on nights something changed.

**Consumers and how they follow the log.**
- `TickerScore.warren_last_buy_fired_at` and `EtfScreenerRow.warren_last_buy_fired_at`: `last_buy_signal_fired_at` = newest Blue/Yellow/Gray Up in the log, copied to the read-models by the 03:25 score recompute / the ETF job. After a reconcile the Warren job refreshes them itself (`refresh_warren_score_fields`) for the tickers whose events changed, so they cannot disagree with the log in between. `warren_active_signal_kind` is NOT derived from the log (it is the latest-state row's kind, rewritten by the same job); it is refreshed in the same call.
- Daily-chart markers (`chart_data._warren_signal_markers`): read at request time, one marker per (day, kind), so they follow the log at once.
- Opportunities: the weekly B3 rule (`opportunity_data.load_signal_status`: a Blue/Yellow Up in the last 10 sessions) is read when the weekly run is built; the daily D1 flags (`opportunity_daily_data._load_events`) read events at flag time using `created_at` ("knowable"). Stored runs, pool rows and flags are history and are not rewritten (CRM's 10-09 pool row says `fired` because of its phantom).

**Dry run on the live database (cached bars only; nothing written).** 136 tickers, 65 change, **141 events deleted, 0 added**, 2,434 matching events untouched, 0 refused, 0 without bars, 0 failed; the set equals the Part 1 phantom set exactly. Consumer changes today: `warren_last_buy_fired_at` changes for CRM (2026-09-29 14:30 -> 2026-06-23 10:30), DELL (2026-01-07 15:30 -> 2025-12-19 10:30), HWM (2026-09-11 12:30 -> 10:30, same day), MEDP (2026-09-02 10:30 -> 2026-04-27 12:30) and ROBO (ETF row 2026-10-15 15:30 -> 2026-09-11 10:30; ROBO has no TickerScore row); B3 "fired" changes for ROBO only (True -> False); INTC and META change nothing (their real arrows stay); 109 daily-chart markers disappear across 60 tickers; no stored D1 flag sits on a deleted day.

**Live cleanup plan (not run).** (1) Merge the branch, deploy. (2) Back up just the events: export `WarrenSignalEvent` (all rows, about 3,337 today, tiny) to a file outside the database (for example CSV or a small sqlite file from a read-only SELECT), plus the current `warren_last_buy_fired_at` / `warren_active_signal_kind` of TickerScore and EtfScreenerRow for the affected tickers. (3) Expected: 65 tickers, 141 deletes, 0 adds, 2,434 untouched, 3,337 -> about 3,196 rows; five score-row refreshes. (4) Run `reconcile_warren_events` (dry run first, then `--apply`), then the dry run again (expect 0). Restore = re-insert the exported rows. If the merge happens before the cleanup, the first nightly run does the same reconcile on its own.

### Event log reconcile: merged, applied and verified (2026-10-18)

- **Suite:** full backend suite on branch `warren-event-reconcile` (`0958902`): **6025 passed, 0 failed, 0 errors**, 1037 s (07:11-07:28 UTC), including `test_warren_signal_data.py` and `test_chart_2h.py`, which had not been run before the change.
- **Export before anything was written** (outside the repo, never committed): `/home/shen/backups/warrensignalevent_20261018_072929.json` (all 3,337 `WarrenSignalEvent` rows with their column names, 367,578 bytes) and `/home/shen/backups/warren_score_fields_20261018_072929.json` (`warren_last_buy_fired_at` and `warren_active_signal_kind` of all 612 `TickerScore` and 28 `EtfScreenerRow` rows, 18,345 bytes). Row counts equal the database's.
- **Old backup deleted:** `backend/fathom_pre_stateless_20261017_121242.db` and its `-wal` / `-shm` stubs (free disk 1.5 GB -> 2.8 GB). The database has no whole-file backup of its own from before the stateless replay any more: **the revert for the watch table is now `git revert` of the merged commits plus a rebuild of the rows from the cached bars** (the nightly replay is stateless, so reverting the code and letting the next nightly run, or `rebuild_warren_watch.py`, rewrites the rows). The nightly 03:30 backup still exists as the whole-database restore point.
- **Merged** into `main` as a fast-forward (`85328d0` -> `0958902`), not pushed. The merged diff touches `data/warren_signal_data.py`, which the app imports (chart, Screener score, ETF refresh), so the app was restarted the documented way (`./bin/stop.sh`, `./bin/start.sh --prod`): `/api/health` 200, the warren route 401 unauthenticated, no errors in the app log; cron untouched (Warren entry `25 1 * * *`).
- **Dry run before apply** matched the plan exactly: 136 tickers, 65 change, 141 events to delete, 0 to add, 2,434 matching events untouched, 0 refused, 0 without bars, 0 failed.
- **Applied once** (`reconcile_warren_events.py --apply`, 07:32 UTC): 141 deleted, 0 added, 65 tickers, 5 score rows refreshed; events 3,337 -> 3,196 (162 tickers). A second dry run reports 0 changes. The five rows changed are exactly the planned ones: CRM `2026-09-29 14:30` -> `2026-06-23 10:30`, DELL `2026-01-07 15:30` -> `2025-12-19 10:30`, HWM `2026-09-11 12:30` -> `10:30`, MEDP `2026-09-02 10:30` -> `2026-04-27 12:30` (TickerScore) and ROBO `2026-10-15 15:30` -> `2026-09-11 10:30` (ETF row; ROBO has no TickerScore row). ROBO's B3 "fired" is now false; INTC (fired, `2026-10-13 14:30`) and META (`2026-08-20 15:30`) are unchanged. The watch table was not touched (117 rows, newest `last_updated_at` still `2026-10-18 01:28:48`).
- **Restore procedure for events:** re-insert the rows of `/home/shen/backups/warrensignalevent_20261018_072929.json` (`columns` + `rows`; the table has a unique key on ticker, timeframe, fired_at, signal_kind, so insert with `INSERT OR IGNORE` after deleting the table's rows, or only the 141 deleted ones), and restore the score fields from the second file. Nothing else was changed by the cleanup.

