# Reversal-Candidate History Investigation — 2026-09-13

Investigation only, no code changes. Follow-up to
`pullback_history_investigation_2026-09-13.md`'s own §3 scope-check, which
flagged Reversal (`ReversalCard.tsx`, downtrend-only) as carrying the
identical "shows only the latest state, no record of how it got there" gap
Pullback Recovery had — but explicitly noted it as "not a free bundle...
a different code path than §2's fix," worth its own investigation rather
than assumed free. This is that investigation.

## 1. Does `trend_started` already work correctly for downtrends?

**Yes — confirmed against real cached data, no separate work needed.**
`trend_started`/`flip_swing` is written by exactly one field on
`TrendMachineState` (`state_machine.py`), set identically regardless of
which direction is flipping into — there is no uptrend-specific branch
anywhere in `run_state_machine` that a downtrend equivalent could be
missing.

Queried `backend/fathom.db`'s live `trendanalysis` table directly (172
rows currently read `trend_state='downtrend'`):

- **Genuine-flip case** (`trend_started_is_lower_bound=0`) — SNAP, SOFI,
  ZTS, XYL, WYNN all show `trend_started_json` populated with
  `"classification": "LL"`, exactly the primary-for-downtrend swing type
  `_PRIMARY_FOR_DIRECTION["downtrend"] == "LL"` names. SNAP's reads
  `{"date": "2026-02-17", ..., "classification": "LL"}` under a downtrend
  first observed by this ticker's own row — a real, confirmed flip.
- **Bootstrap/lower-bound case** (`trend_started_is_lower_bound=1`) — 3 of
  the 172 downtrend rows (FDXF, HONA, PARA) hit this branch. FDXF's is the
  most informative: `trend_started_json` reads `"classification": "LH"`,
  **not** `"LL"` — and this is correct, not a bug. The bootstrap sets
  `flip_swing = classified[0]` (state_machine.py:127-136) regardless of
  whether that first-ever classified swing happens to be the
  *primary*-for-direction type or not; the trend direction itself is
  bootstrapped from `classified[0]`'s own bullish/bearish grouping
  (`_direction_of`), which only requires "LH or LL" (both bearish), not
  specifically "LL". So a downtrend that has never genuinely flipped since
  cached history began can correctly report its `trend_started` as an LH
  swing — this is the exact "predates tracked history, no real flip rule
  applies" case §1 of the prior investigation flagged as a real design
  decision, and it demonstrably fires correctly for downtrends in
  production data today.

Both branches are exercised by the shared, direction-agnostic code path;
nothing about `flip_swing`/`trend_started` reads `trend_state` to decide
*whether* to set the field, only *what value* to set (`_to_detail(cs)` on
whichever swing triggers the branch). **No work needed here.**

## 2. Scoping `reversal_history`

### What it needs to hold, and why it's a different shape than `pullback_history`

`pullback_history` records **completed two-point cycles** — a warning
swing (a confirmed LH-while-uptrend or HL-while-downtrend) paired with the
same-direction confirming swing that later resolved it. It already exists
and is already computed symmetrically for both trend directions today —
confirmed directly against the same real downtrend rows above: SNAP's
`pullback_history_json` holds 4 real `{warning_swing (HL), resolving_swing
(LH)}` cycles from its current downtrend (e.g. warning on 2026-04-23,
resolved 2026-05-01), ZTS's holds 7. **This is not what the task is
asking for** — it's the downtrend-side mirror of Trend Continuation's own
"pullback against the prevailing trend, then continuation" cycle, already
fully functional, and orthogonal to reversal candidates.

What Reversal actually needs is structurally simpler: a list of
**single-point events** — every confirmed LL swing that has occurred
*within the current downtrend*, each carrying its own
`ad_bullish_divergence`/`ad_divergence_swing_date` (both already computed
per-swing by `classify_swings`, just never retained past "most recent
one" — see §3). Proposed shape, mirroring `PullbackCycle`'s placement in
`types.py`:

```python
@dataclass(frozen=True)
class ReversalCandidate:
    swing: SwingDetail  # date/price/margin/atr/ratio/classification ("LL")
    ad_bullish_divergence: bool
    ad_divergence_swing_date: date | None
```

- `TrendAnalysisOut.reversal_history: list[ReversalCandidateOut]`, oldest
  first — same "reset on genuine flip" lifecycle boundary as
  `pullback_history`/`trend_started`.
- Storage: same Option-A precedent from the prior investigation
  (`LiquidityZoneAnalysis`'s bounded JSON-list-on-a-latest-only-row shape,
  already reused once for `pullback_history_json`) — a new
  `reversal_history_json` column on `TrendAnalysis`, nullable, via
  `_add_missing_columns`, no migration tooling needed. No new table, no
  backfill, no pruning job.

### One real open design question: does the flip-triggering LL itself belong in the list?

`pullback_history` is reset to `[]` in the flip branch and the
flip-triggering swing is deliberately **excluded** from it — that's
correct there, because a flip event and a "pullback cycle" are
categorically different things (a trend-state transition vs. a completed
pause-then-continue pair). `reversal_history` doesn't have that same
categorical distinction: the swing that flips a trend into a downtrend
*is itself* a confirmed LL — exactly the same kind of event every later
same-direction confirmed LL in that downtrend would also be. If
`reversal_history` mechanically resets to `[]` on flip the same way
`pullback_history` does, and the flip-triggering LL is never appended
anywhere else, then a freshly-flipped downtrend with no further confirmed
LL yet would show an **empty** `reversal_history` even while
`last_confirmed_swing`/`ReversalCard`'s own "Confirmed" checklist item is
already showing that exact LL as satisfied — a visible inconsistency
between the card's headline status and its own history list.

**Recommendation:** seed `reversal_history` with the flip-triggering LL as
its first entry, in the same flip branch that sets `flip_swing`/
`trend_started` — i.e., append before (or instead of) resetting to `[]`,
not after. This is a one-line difference from the `pullback_history`
precedent, not a structural one, but worth flagging explicitly as a
deliberate deviation rather than copy-pasting the reset behavior verbatim
and producing a silently misleading empty list on the most common case
(a freshly-flipped, still-young downtrend).

### UI shape: not a direct reuse of `PullbackHistoryTimeline`

The task's own framing is right: `PullbackHistoryTimeline`
(`TrendContinuationCard.tsx`) flat-maps `{warning_swing, resolving_swing}`
pairs into an **alternating two-color sequence** (warning dot, resolved
dot, warning dot, resolved dot...) — it has no notion of a single
independent point with its own boolean state. `reversal_history` needs a
different mapping: **one dot per list entry**, colored by
`ad_bullish_divergence` (e.g. accent/positive dot when divergence was
present at that LL, neutral dot otherwise), not by an alternating
kind. The underlying DOM/layout (horizontal scrollable row, connecting
hairline, dot + small date caption underneath) is close enough to
`PullbackHistoryTimeline`'s that a shared low-level "row of dots with
captions" primitive would be a reasonable extraction *at implementation
time* — but the data-shape function (`pullbackHistoryPoints`'s
equivalent) and the color key are genuinely different, so this is "new
sibling component, possibly sharing a primitive," not "reuse
`PullbackHistoryTimeline` as-is."

## 3. Where does this accumulation belong — `classify_swings()` or `state_machine.py`?

**`state_machine.py::run_state_machine`, not `classify_swings()` — confirmed
by reading both, not assumed.** This is the one place the task asked to
verify carefully, and it's a real, load-bearing distinction:

- `classify_swings()` (`classification.py`) has **no concept of
  `trend_state` or trend-segment boundaries at all**. Its own
  `confirmed_ll_osc_lows` accumulator (used to build the trailing-3
  divergence floor) accumulates across **every** confirmed LL in the
  ticker's entire classified history, unconditionally — it is never reset,
  and specifically does **not** reset at what a caller would consider a
  "new downtrend." This is deliberate, validated backtest behavior (the
  module's own docstring: "compares... against a rolling floor built from
  the trailing 3 prior confirmed... LL swings' own matched lows"), not an
  oversight — the divergence rule's own trailing-3 floor is explicitly
  NOT scoped to "current downtrend."
- `run_state_machine()` (`state_machine.py`) is the **only** layer that
  knows what "current downtrend" means at all — it's the one place
  `trend_state` is tracked and flips are detected, and it's exactly where
  `pullback_history`/`flip_swing`/`pullback_occurred_since_flip` already
  reset on a genuine flip. It already visits every classified swing once,
  in order, and already distinguishes the "same-direction, classification
  is the primary type" case from every other case — LL-while-downtrend
  swings pass through the `same_direction` branch (state_machine.py:143-158)
  exactly where `last_confirmed_swing` gets updated. Appending to a new
  `reversal_history` accumulator there, alongside the existing
  `pullback_history` append logic, requires **zero new iteration** — same
  single pass, same trigger point (a same-direction, ratio≥`CONFIRMED_RATIO`
  swing whose `classification == "LL"`), reset to `[]` on every genuine
  flip exactly like `pullback_history`/`trend_started` already are.

**Complication actually found (documented in §2 above, not new here):**
because `classify_swings()`'s own divergence floor ignores trend-segment
boundaries, an early confirmed LL within a brand-new downtrend can have
its `ad_bullish_divergence` computed against a trailing-3 floor that
reaches backward across the flip, into confirmed LLs from a **prior**
downtrend the ticker had before the intervening uptrend. This is not a
new problem `reversal_history` introduces — it's already true of the
single `ad_bullish_divergence` value the engine surfaces today (`engine.py`'s
own `confirmed_lls` selection scans the **entire** multi-trend `classified`
list and takes the last entry overall, with no trend-boundary filter
either) — but it's worth stating explicitly for whoever implements this:
scoping the *list* to the current downtrend does not, and should not,
require re-deriving each entry's already-computed divergence flag: the
scoping is a state_machine-level list-membership question ("was this LL
confirmed while this same downtrend was active"), while each entry's own
`ad_bullish_divergence` value keeps its existing, validated,
trend-boundary-agnostic definition unchanged.

**One more precondition worth naming:** `engine.py`'s own top-level
`ad_bullish_divergence`/`ad_divergence_swing_date` selection (lines 63-70)
would need no change either. It already selects "the ticker's most recent
confirmed LL swing" off the full `classified` list independent of current
`trend_state` — which is currently harmless only because `ReversalCard`
is never rendered at all while `trend_state == "uptrend"`
(`technicalCardScope.ts` mounts `TrendContinuationCard` instead) and its
own gate additionally requires `last_confirmed_swing.classification ==
"LL"`, which the state-machine invariant guarantees only holds during a
downtrend. `reversal_history` sidesteps this entirely by living on
`TrendMachineState` (built during the downtrend-aware pass) rather than
re-deriving from the raw `classified` list a second time in `engine.py`.

## 4. `bt_signal1_analyze.py` presence check

**Absent from this checkout — confirmed, not assumed, same situation as
`bt_signal2_analyze.py`.**

- `find . -iname "*bt_signal1*"` and `ls backend/scripts/`: no such file
  or directory exists anywhere in the current working tree.
- `git log --all -S"bt_signal1_analyze"`: exactly one hit,
  `5e8055c` ("Add Reversal/Trend Continuation checklist cards to the
  Technical tab") — the commit that *cites* the script's already-completed
  results, both in its commit message and in `ReversalCard.tsx`'s own
  comments. The script itself was never committed.
- This matches `CLAUDE.md`'s documented convention for `backend/scripts/`
  ("untracked, ad-hoc research tooling that never touches production
  data... Not committed to git") and the identical finding the prior
  investigation made for `bt_signal2_analyze.py`.
- The commit message states both scripts' findings directly: Reversal's
  edge is "a real but modest ~1-month directional edge that decays to
  indistinguishable-from-noise by 3-6 months," and the "mature prior
  downtrend" persistence filter from the original scope made the
  ticker-clustered edge *weaker*, so it was dropped — both already fully
  reflected in `reversalStatus()`'s shipped implementation (`ReversalCard.tsx`)
  and its `DISCLAIMER` text. There is no indication either script is
  re-run on a schedule or reads live data going forward.

An additive `reversal_history` field carries the same low risk this class
of change already carries by precedent (per the prior investigation's
identical reasoning for `bt_signal2_analyze.py`): every consumer in this
codebase reads dataclass/Pydantic fields by name, never by position, so a
new field cannot silently perturb whatever the backtest script (if a local
uncommitted copy still exists and is still run) reads today.

## Summary

| Question | Finding |
|---|---|
| §1 `trend_started` for downtrends | Already works, confirmed against real data (SNAP/SOFI/ZTS/XYL/WYNN genuine-flip; FDXF/HONA/PARA bootstrap/lower-bound). No work needed. |
| §2 `reversal_history` shape | New `list[ReversalCandidate]` (single-point events, not pairs) on `TrendMachineState`/`TrendStructureResult`/`TrendAnalysisOut`, JSON column on `TrendAnalysis` (Option A precedent, same as `pullback_history`). Open decision: seed the list with the flip-triggering LL itself (recommended), unlike `pullback_history`'s exclusion. |
| §3 Which layer owns this | `state_machine.py::run_state_machine`, not `classify_swings()` — confirmed `classify_swings()` has no trend-segment concept at all. Fits into the existing single pass, same reset trigger as `pullback_history`. One documented pre-existing quirk (divergence floor ignores trend boundaries) carries over unchanged, not a new complication. |
| §4 `bt_signal1_analyze.py` | Confirmed absent from this checkout; same situation and same low-risk conclusion as `bt_signal2_analyze.py`. |

Scoped as its own follow-up, not a trivial bundle — the state-machine
change is small and follows an existing template closely, but it is a
genuine second accumulator with its own reset semantics and one real
design decision (the flip-swing seeding question in §2) that wasn't
already settled by the `pullback_history` precedent.
