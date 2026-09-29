# Trend structure analysis (Technical tab)

A read-only lens on price structure — swing highs/lows, break-of-structure (BOS) flips, and a
blended -10..+10 conviction score — computed from FMP daily bars via the shared bars cache, not
the fundamentals pipeline. Never touches Step 1-5/Overall Assessment scoring or any other lens —
a parallel data path from ingestion through to display. See `CLAUDE.md`'s "Trend structure
analysis (Technical)" section for the full swing/BOS/A-D-divergence/SMA-position mechanism,
which this document does not repeat; this document covers the three fields (`trend_started`,
`pullback_history`, `reversal_history`) that mechanism section leaves undocumented.

## Why these three fields exist

Two review-flagged UX gaps on the Technical tab's Near-term/Pullback-recovery and Reversal cards
motivated a 2026-09-13 investigation, then a same-day build:

1. **"Turned up on" drifts away from the real flip date** as `persistence_count` accumulates —
   the card needed to show *when the current trend actually began*, not just the most recent
   re-confirming swing.
2. **No visibility into how many pullback-and-recovery cycles have already happened** within the
   current trend, or (for a downtrend) how many confirmed lower-low reversal candidates have
   occurred, each with its own A/D-divergence read.

Both investigations found the same shape of gap already solved once, for a different lens:
Weinstein Stage Analysis's `weinstein_stage_since_date`/`_is_lower_bound` (see
[Weinstein Stage](weinstein-stage.md)) already answers "when did the *current* state begin," and
that same lower-bound convention is reused here rather than reinvented.

## `trend_started` (the real flip date)

`state_machine.py::run_state_machine` already identifies the exact swing that triggers a genuine
flip at one call site. `state.flip_swing` is set there, reusing the existing `SwingDetail` type
verbatim — no new dataclass. Surfaced as `TrendAnalysisOut.trend_started`.

**Bootstrap semantics, a real design decision, not just plumbing.** The module's own docstring
is explicit that the very first classified swing bootstraps `trend_state` by assumption — "the
spec has no rule for 'what was the trend before any flip occurred.'" Concretely,
`run_state_machine`'s loop starts at `classified[0]` itself, and since `trend_state` was already
seeded to that swing's own direction, `classified[0]` always lands in the same-direction branch,
never the flip branch — so a naive implementation would show `trend_started: null` for exactly
the tickers with the longest cached runway (any ticker whose current trend has never flipped
since cached history began).

**Fixed the same way Weinstein Stage's own "since" field is**: `flip_swing` is populated from
`classified[0]` on bootstrap too, paired with `flip_swing_is_lower_bound: bool` (surfaced as
`TrendAnalysisOut.trend_started_is_lower_bound`) — rather than leaving it `null`, the field
reports the earliest available swing as a lower bound, honestly labeled as "predates tracked
history" rather than "never flipped."

Confirmed against real cached data (SNAP, SOFI, ZTS, XYL, WYNN — genuine-flip case,
`trend_started_is_lower_bound=0`; FDXF, HONA, PARA — bootstrap/lower-bound case). One subtlety
confirmed directly: the bootstrap sets `flip_swing = classified[0]` regardless of whether that
first-ever classified swing happens to be the *primary*-for-direction type or not (a downtrend's
bootstrap `trend_started` can correctly read `"classification": "LH"`, not `"LL"`, since the
direction itself is bootstrapped from `classified[0]`'s bullish/bearish grouping, which only
requires "LH or LL," not specifically the primary type).

## `pullback_history` (completed warning→resolution cycles within the current trend)

`run_state_machine` already visits every classified swing once and already distinguishes (a) a
swing that sets a warning, (b) a same-direction confirming swing that clears a pending warning,
and (c) a flip, which implicitly closes out any still-open warning as "invalidated" rather than
"resolved." A `PullbackCycle(warning_swing, resolving_swing)` is appended to a
`pullback_cycles: list[PullbackCycle]` accumulator at case (b), and the list is reset to `[]` at
every genuine flip (the same trigger `persistence_count` resets on).

**Storage shape, a real decision.** Two live precedents existed for "more than the single latest
state": a bounded JSON list on the existing `TrendAnalysis` row (mirroring
`LiquidityZoneAnalysis.support_zones_json`), or a real accumulating event table (mirroring
`WarrenSignalEvent`). The bounded-JSON-list option was chosen — the task ("within the current
trend," "mini-timeline") matches it exactly, at a fraction of the cost (no new table, no pruning
cron), and the list is naturally self-bounding since it resets on every flip. A real event table
across *every* trend a ticker has ever had would be a materially bigger feature, not a
refinement of this one. Confirmed via real cached history that "small" is genuinely small even
for an unusually persistent multi-year trend (one real 2.3-year uptrend contained 9 separate
warning→resolution cycles before eventually flipping without one final warning ever resolving).

Storage: `pullback_cycles_json` column on `TrendAnalysis` (nullable, `_add_missing_columns`),
reset to `"[]"` every genuine flip. Surfaced as `TrendAnalysisOut.pullback_history: list[
PullbackCycleOut]`, oldest first.

## `reversal_history` (confirmed LL swings within the current downtrend, each with its own A/D-divergence read)

A structurally different shape than `pullback_history` — **single-point events**, not pairs:
every confirmed LL swing that has occurred *within the current downtrend*, each carrying its own
`ad_bullish_divergence`/`ad_divergence_swing_date` (both already computed per-swing by
`classify_swings`, just never retained past "most recent one" before this build). Feeds
`ReversalCard.tsx`'s own dot-timeline.

**Design decision: seed with the flip-triggering LL, unlike `pullback_history`'s exclusion.** A
flip event and a "pullback cycle" are categorically different things (a trend-state transition
vs. a completed pause-then-continue pair), so `pullback_history` correctly excludes the
flip-triggering swing. `reversal_history` has no such categorical distinction — the swing that
flips a trend into a downtrend *is itself* a confirmed LL, exactly the same kind of event every
later same-direction confirmed LL in that downtrend would also be. Mechanically resetting to
`[]` on flip and never appending the flip-triggering LL anywhere else would show an **empty**
`reversal_history` for a freshly-flipped downtrend even while `last_confirmed_swing`/
`ReversalCard`'s own "Confirmed" checklist item already shows that exact LL as satisfied — a
visible inconsistency between the card's headline status and its own history list. Fixed by
appending the flip-triggering LL as the list's first entry in the same flip branch that sets
`flip_swing`/`trend_started`, and only when flipping *into* a downtrend (flipping into an
uptrend resets to `[]` unconditionally — `reversal_history` has no meaning outside a downtrend).

**Which layer owns this — confirmed, not assumed.** `classify_swings()` (`classification.py`)
has no concept of `trend_state` or trend-segment boundaries at all; its own
`confirmed_ll_osc_lows` accumulator (the trailing-3 divergence floor) accumulates across *every*
confirmed LL in the ticker's entire classified history, unconditionally, and is deliberately
**not** scoped to "current downtrend" — that's validated backtest behavior for the divergence
rule itself, not something this feature should disturb. `run_state_machine` is the only layer
that knows what "current downtrend" means, and it already visits every classified swing once, in
order — so `reversal_history` accumulates there, in the same single pass as `pullback_history`,
with zero new iteration.

**One pre-existing quirk, not introduced by this feature and not fixed by it**: because
`classify_swings()`'s own divergence floor ignores trend-segment boundaries, an early confirmed
LL within a brand-new downtrend can have its `ad_bullish_divergence` computed against a
trailing-3 floor that reaches backward across the flip, into confirmed LLs from a *prior*
downtrend the ticker had before an intervening uptrend. This was already true of the single
`ad_bullish_divergence` value the engine surfaced before this feature existed (`engine.py`'s own
`confirmed_lls` selection scans the entire multi-trend `classified` list with no trend-boundary
filter either); scoping the *list* to the current downtrend is a state-machine-level
list-membership question and does not, and should not, require re-deriving each entry's own
already-computed divergence flag.

Storage: `reversal_history_json` column on `TrendAnalysis` (nullable, same convention as
`pullback_history_json`). Surfaced as `TrendAnalysisOut.reversal_history: list[
ReversalCandidateOut]`, oldest first.

## `trend_started` for downtrends — no separate work needed

Confirmed directly against real cached data (172 live `downtrend` rows) that `flip_swing`/
`trend_started` is written by exactly one field, set identically regardless of which direction
is flipping into — there is no uptrend-specific branch in `run_state_machine` that a downtrend
equivalent could be missing from. Both the genuine-flip and bootstrap/lower-bound branches are
exercised correctly by real downtrend rows in production.

## Backtest-compatibility

The two shipped fields above build on `bt_signal2_analyze.py`'s (Trend Continuation/Reversal
card) and `bt_signal1_analyze.py`'s (the same, an earlier round) already-completed, already-
shipped findings — neither script exists in this checkout (per `CLAUDE.md`'s documented
`backend/scripts/` convention: untracked, ad-hoc research tooling, never committed). Every new
field here is purely additive to `TrendStructureResult`/`TrendAnalysisOut`/`TrendAnalysis`
(dataclass/Pydantic fields accessed by name everywhere in this codebase, never positionally), so
this class of addition carries the same low, already-established risk to any local, uncommitted
copy of either script that might still exist.
