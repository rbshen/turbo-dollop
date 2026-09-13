# Trend-Flip Date + Pullback History Investigation — 2026-09-13

Investigation only, no code changes. Scoped to two review-flagged UX gaps on
the Technical tab's Near-term / Pullback recovery cards: (1) "Turned up on"
drifts away from the real flip date as `persistence_count` accumulates, and
(2) there's no visibility into how many pullback-and-recovery cycles have
already happened within the current trend. A third question checks whether
this is a one-off gap or a pattern shared with other Technical-tab surfaces.

## 1. Flip date (`flip_swing` / `trend_started`)

**Cheap. A same-shape, one-field addition to `TrendMachineState` — no new
type, no new loop, no new fetch.**

`state_machine.py::run_state_machine` already identifies the exact swing
that triggers a genuine flip at one single call site
([state_machine.py:130-141](../backend/analysis/trend_structure/state_machine.py#L130-L141)):

```python
if is_primary and ratio >= CONFIRMED_RATIO:
    state.trend_state = direction
    state.magnitude_tier = _magnitude_tier_for_ratio(ratio)
    state.persistence_count = 1
    state.last_confirmed_swing = _to_detail(cs)   # <- same cs, already built as a SwingDetail
    ...
```

Adding `state.flip_swing = _to_detail(cs)` on this exact line is the entire
change to the hot path — `_to_detail` already exists and already returns the
`SwingDetail` type this would reuse verbatim (no new dataclass needed). The
only other place needing a line is the bootstrap constructor
([state_machine.py:104-111](../backend/analysis/trend_structure/state_machine.py#L104-L111)),
which needs a `flip_swing: SwingDetail | None = None` default — see the
bootstrap-semantics note below for what value (if any) that should carry.

**Downstream field-set assumptions — checked, none found.** Grepped every
`state.<field>` access in the codebase: only `engine.py` (explicit,
named-field reads into `TrendStructureResult`) and `test_state_machine.py`/
`test_engine.py` (per-attribute assertions, or keyword-only construction of
`TrendMachineState` in the one test that builds it directly —
[test_engine.py:173-180](../backend/analysis/trend_structure/test_engine.py#L173-L180)).
Nothing does `dataclasses.asdict(state)`, `vars(state)`, or any other
whole-object/positional access that a new field would perturb. This is the
same additive shape every other field on this dataclass already used
(`pullback_occurred_since_flip` was added the same way, with its own
trailing default). Plumbing is otherwise identical to `last_confirmed_swing`
end to end: `TrendStructureResult.trend_started: SwingDetail | None` →
`TrendAnalysisOut.trend_started: SwingDetailOut | None` (reusing the
existing `SwingDetailOut` model, no new schema) → a new
`trend_started_json` column on `TrendAnalysis`, using the exact same
`_swing_detail_to_json`/`_swing_detail_from_json` helpers
[trend_analysis_data.py:27-58](../backend/data/trend_analysis_data.py#L27-L58)
already serialize `last_confirmed_swing`/`warning_swing` with — copy-paste,
not new code. New column is nullable, added via `core/db.py`'s existing
`_add_missing_columns` sweep (no migration tooling needed, same
add-if-missing convention every other field on this table already uses);
pre-existing rows read `NULL` until the next nightly run, same transient-
read-safety story as `ad_bullish_divergence`/`sma20_cross`/etc.

**One real design decision, not just plumbing — what does `flip_swing` mean
during the bootstrap segment?** The module's own docstring
([state_machine.py:100-103](../backend/analysis/trend_structure/state_machine.py#L100-L103))
is explicit that the very first classified swing bootstraps `trend_state`
by assumption, not by a real flip rule — "the spec has no rule for 'what
was the trend before any flip occurred.'" Concretely: `run_state_machine`'s
loop starts at `classified[0]` itself (not `classified[1:]`), and since
`trend_state` was already seeded to that swing's own direction,
`classified[0]` always lands in the *same-direction* branch, not the flip
branch — so it can set `last_confirmed_swing` (if ratio ≥ 0.5) but would
never set `flip_swing` if that field is only written inside the flip
branch. That's arguably the *correct* reading (no genuine flip has actually
occurred yet), but it means any ticker whose current trend has never
flipped since the cached history began would show `trend_started: null` —
an honest "predates tracked history" answer, but a hole in the UI for
exactly the tickers with the longest cached runway.

This is the identical shape of problem Weinstein Stage Analysis already
solved for its own "since" field, and it's worth mirroring rather than
reinventing: `WeinsteinStageResult.stage_since_date` /
`stage_since_is_lower_bound` walks back to the earliest available week of
the current stage, and when the current stage covers the *entire* available
history (no transition found at all), it reports that earliest week as the
`stage_since_date` anyway with `stage_since_is_lower_bound=True`, rather
than `null` (see `WeinsteinStageResult`'s own docstring,
[types.py:131-137](../backend/analysis/trend_structure/types.py#L131-L137)).
Recommend the same shape here if this ships: populate `flip_swing` from
`classified[0]` on bootstrap too, paired with a `trend_started_is_lower_bound:
bool` flag, rather than leaving it `null` for every long-running,
never-flipped ticker. This is a few extra lines beyond the MVP one-liner
above, not a redesign — flagging it now so it's a deliberate choice, not an
oversight discovered after ship.

**Frontend surface**: `NearTermCard.tsx`'s `turnedOnLabel`/"Turned up on"
row would switch from `data.last_confirmed_swing.date` to
`data.trend_started.date` — a one-line change once the field exists, with
`last_confirmed_swing` staying exactly where it is today (it's still the
right field for "when was the trend last re-confirmed," a distinct and
still-useful fact, not something this deprecates).

## 2. Pullback history (past warning→resolution cycles within the current trend)

**Small addition to the existing single-pass loop, not a redesign** — the
mechanism is genuinely cheap. **Does change the shape of `TrendAnalysisOut`
and DB storage**, but there's already a directly-reusable precedent for
exactly this shape in this codebase, so it's a "reuse a pattern," not
"invent one."

### The loop-level change is trivial

`run_state_machine` already visits every classified swing exactly once and
already knows, at each iteration, whether it's looking at (a) a swing that
sets a warning (`state.warning_flag = True`, in the "not `is_primary`"
branch,
[state_machine.py:142-150](../backend/analysis/trend_structure/state_machine.py#L142-L150))
or (b) a same-direction confirming swing that *clears* a pending warning
(the `if warning_flag:` check inside the same-direction branch,
[state_machine.py:118-128](../backend/analysis/trend_structure/state_machine.py#L118-L128))
or (c) a flip, which also implicitly closes out any still-open warning as
"invalidated" rather than "resolved" (the flip branch already zeroes
`warning_flag`/`warning_swing` — the difference between "resolved" and
"invalidated" as a *reason* would need one extra bit of information
threaded through, since today both paths just silently clear the same two
fields with no record of which case occurred). Appending a
`(warning_swing, resolving_swing, resolution)` tuple to a
`pullback_cycles: list[PullbackCycle]` accumulator at cases (b)/(c) above,
and resetting that list to `[]` at every genuine flip (same place
`persistence_count` resets to 1), is the entire algorithmic change — no
second pass, no new fetch, no new classification logic. This is the same
"fold into the existing loop" shape A/D Bullish Divergence already used
successfully when it was added to `classification.py`'s own single pass.

I confirmed this against CTAS's own real cached history (from the prior
Technical-tab investigation this session): its 2022-08-18 → 2024-12-19
uptrend alone (2.3 years, `persistence_count` reaching 62) contains **9
separate warning→resolution cycles** before the trend eventually flipped
without one final warning ever resolving (Invalidated). That's a real,
bounded number — not evidence of runaway list growth, but a useful sanity
check on how big "small" actually is for a long-running trend.

### Where this needs a real decision: storage shape

Two live precedents already exist in this codebase for "more than the
single latest state," and they represent genuinely different cost/scope
tradeoffs:

**Option A — bounded JSON list on the existing `TrendAnalysis` row**,
mirroring `LiquidityZoneAnalysis.support_zones_json`/`resistance_zones_json`
(a JSON string holding a list of `{price, cluster_size, formed_at}`
objects, on an otherwise latest-only table). A new
`pullback_cycles_json` column on `TrendAnalysis`, holding a list of
`{warning_swing, resolving_swing, resolution}` objects, reset to `"[]"`
every genuine flip. This is the cheaper option and the one that actually
matches what was asked for ("within the current trend") — no new table, no
pruning job, no backfill, same nullable-column/`_add_missing_columns`
convention as everything else on this row. List length is naturally
self-bounding (reset on every flip), and CTAS's own 9-cycle trend suggests
"dozens, not thousands" even for an unusually persistent multi-year trend.

**Option B — a real accumulating event table**, mirroring
`WarrenSignalEvent`/`TechnicalEntrySignalEvent` (surrogate PK, append-only,
never overwritten, pruned by age via a `sweep_stale_*`-style job). This is
the right shape *if* the actual product intent is a full historical
timeline across *every* trend a ticker has ever had, not just the current
one — i.e., if "mini-timeline UI" means more than what Option A's
per-trend list already provides. Notably, this would need **no separate
backfill script** the way `backfill_entry_signal_events.py` was needed for
BB+RSI: the swing/BOS engine already replays a ticker's *entire* cached
history from scratch on every compute (same as Warren's own signal, which
is why *it* didn't need a backfill script either) — so the very first
nightly run under this feature would already reconstruct every historical
cycle, no gap-filling needed.

**Recommendation:** Option A. The task as scoped ("within the current
trend," "mini-timeline") matches Option A's shape exactly, at a fraction of
the implementation cost (no new table, no migration-adjacent PK/constraint
design, no pruning cron). Option B is worth keeping in mind only if a
future ask genuinely wants "every pullback this ticker has ever had,"
which is a materially bigger feature, not a refinement of this one.

### `TrendAnalysisOut` shape impact

Either option adds one new field (`pullback_cycles: list[PullbackCycle]` on
the `TrendAnalysisOut`/frontend-type side); Option A needs one new
`SwingDetailOut`-shaped nested pair per cycle (reusing the existing type,
same as `flip_swing` above) plus a `resolution: "resolved" | "invalidated"`
literal — no genuinely new primitive types either way. This is additive to
`TrendAnalysisOut`, not a breaking reshape — every existing field
(`warning_flag`, `warning_swing`, `pullback_occurred_since_flip`) stays
exactly as-is; `pullback_occurred_since_flip` in particular remains useful
as a fast boolean the new list would otherwise force a `len() > 0` check to
reconstruct.

### Backtest-compat check (`bt_signal2_analyze.py`)

**Could not inspect the script directly — it does not exist in this
checkout.** `backend/scripts/` is documented in `CLAUDE.md` as
"untracked, ad-hoc research tooling... not committed to git," and that's
confirmed here: `git log --all -S"bt_signal2_analyze"` finds exactly one
hit, the commit that *shipped* `TrendContinuationCard.tsx`/`ReversalCard.tsx`
citing the script's already-completed results in its commit message and
in-code comments — the script itself was never committed, and `ls
backend/scripts/` currently shows no such directory at all in this working
copy. So this can't be verified by reading the script; it can only be
reasoned about from precedent and from what the shipped code tells us it
did.

What we know for certain: the investigation this script produced is
**already fully consumed and baked into shipped logic** — the commit
message for `5e8055c` states its two findings directly (dropping an
"established uptrend" filter for Trend Continuation; dropping a "mature
prior downtrend" filter for Reversal) and both are already reflected in
`resolutionStatus()`/`reversalStatus()`'s current implementation. There is
no indication the script is re-run on a schedule, wired into CI, or reads
live `TrendAnalysisOut`/DB rows going forward — it reads like a one-shot
backtest tool whose output is a written report, already actioned, not a
piece of standing infrastructure. Given it's absent from the repo, there's
nothing here that this change could concretely break by running it again.

The one thing worth flagging rather than asserting: I can't rule out the
possibility the user has a local, uncommitted copy of the script that they
still run. If so, the general codebase convention (every backtest/one-off
script and every dataclass/Pydantic model in this repo is accessed by named
field, never positional tuple/dict-iteration) means an *additive* field is
low-risk by construction — but this is inference from pattern, not a read
of the actual file. Worth a direct check-in with whoever last ran it before
shipping, rather than treating "probably fine" as confirmed.

## 3. Scope check: is this Pullback-recovery-specific, or a wider pattern?

**It's a wider pattern, not unique to Pullback recovery** — three other
Technical-tab/header surfaces have the identical "shows only the latest
state, no record of how it got there" shape, at three different levels of
severity:

- **Weinstein Stage Analysis** (`WeinsteinStagePill`, `WeinsteinStageCard`)
  — **partially already solved**, and the closest thing to a working
  template for this exact ask. `weinstein_stage_since_date` +
  `weinstein_stage_since_is_lower_bound` already answer "when did the
  *current* stage start" (exactly the flip-date problem in §1, solved a
  week earlier for a different lens) — but there is no equivalent list of
  *past* stage transitions (e.g. "this ticker has cycled Base→Advance→Top→
  Decline 3 times in the last 2 years"). Same gap as Pullback history in
  §2, just never asked for on this lens. Cheap to add for the identical
  reason §2 is cheap: `compute_weinstein_stage` already computes the full
  weekly `stage_df` series in one shot every run
  ([weinstein.py:184](../backend/analysis/trend_structure/weinstein.py#L184))
  and only ever reads its very last row today — a transition list is a
  single extra scan over an array that's already sitting in memory, not a
  new computation.

- **Reversal** (`ReversalPill`/`ReversalCard`) — same shape as Pullback
  recovery, and arguably *more* exposed to the "latest state overwrites the
  prior one" problem: `ad_bullish_divergence`/`ad_divergence_swing_date`
  are explicitly scoped by the engine to "the ticker's MOST RECENT
  confirmed LL swing" only
  ([types.py:83-88](../backend/analysis/trend_structure/types.py#L83-L88)),
  so a ticker that had a confirmed reversal-with-divergence six months ago,
  then several more confirmed LLs since without divergence, shows nothing
  today — there's no way to tell "never had a divergence signal" from "had
  one, and it's since scrolled off." This is the same overwrite problem
  §2 addresses, just for a different field the state machine doesn't
  already track a history of at all today (would need `classify_swings`,
  not `run_state_machine`, to accumulate a divergence-events list — a
  different code path than §2's fix, so not a free bundle even though the
  UX complaint rhymes).

- **BB+RSI / Warren entry signals** — **already fully solved**, and the
  precedent both §1 and §2 above borrow their storage design from
  (`TechnicalEntrySignalEvent`/`WarrenSignalEvent`, feeding the Chart tab's
  marker history). Not a gap; cited here only as the existing proof that
  this class of problem has a known, shipped answer in this codebase when
  the product need justifies a full event history.

**Recommendation on bundling**: Weinstein's "since" field is genuinely
free to bundle with §1's `flip_swing` work in the same round — same
shape, same tiny cost, same reviewer already primed on the concept from
the Pullback-recovery ask. Weinstein's *transition history* and Reversal's
*divergence history* are each real, independent gaps worth a ticket, but
neither is a natural freebie off the back of §1/§2's specific code paths —
recommend scoping them as their own follow-ups rather than inflating this
round.
