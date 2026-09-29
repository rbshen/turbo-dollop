# Chart-tab technical indicator implementation notes

Notes on matching a Chart-tab indicator's exact math to a specific third-party reference
platform, so a user comparing Fathom's chart against ThinkOrSwim/TradingView sees the same
numbers. This is a natural home for future indicator-parity write-ups of the same shape — right
now it holds one: the Full Stochastic fix.

## Full Stochastic (5, 3, 3): SMA → EMA, ThinkOrSwim parity (2026-09-25)

### The gap

`analysis/trend_structure/stochastic.py::compute_stochastic` computed Full Stochastic (5, 3, 3)
using **SMA** smoothing (`rolling(3).mean()` applied twice to the raw %K). The user's reference —
ThinkOrSwim's `StochasticFull` study at K=5, slowing=3, D=3, **EXPONENTIAL** — uses classic
recursive EMA smoothing (alpha = 2/(n+1) = 0.5) for both the FullK and FullD stages instead.
Everything else about the calculation already matched: periods (5/3/3), smoothing order (ratio
then average), and the window convention (rolling 5, current bar included).

**Only one implementation of this indicator exists anywhere in the app** — confirmed by grep —
used only by the Chart tab's own Stochastic sub-pane (all 4 ranges: D_6M/D_1Y/D_2Y daily,
W_4Y weekly resampled from the FMP long-history store). Nothing else in the app (Screener,
Watchlist, any of the Technical-tab signals) reads this value, and no crossover logic exists
anywhere on top of it.

### Measured impact, before fixing

A faithful reference EMA implementation, run on the same cached daily bars, agreed with the
shipped SMA output to within floating-point noise (~7e-14) when *both* were computed with SMA
smoothing — confirming the port itself was faithful and SMA-vs-EMA was the *only* difference
being measured. With EMA smoothing instead, the two diverged materially: typical gaps of 5-7
points mean, up to 14-23 points on individual bars, across a sample of large-cap and leveraged-
ETF tickers. The two series differed from essentially the very first computable bar of any
lookback window (not primarily a warm-up-sensitivity issue) and disagreed on which bars actually
crossed the 80/20 overbought/oversold lines and on where %K crossed %D — i.e. the SMA version
wasn't just numerically off, it read differently on the exact events a trader would act on.

**Confirmed the EMA seed choice doesn't matter for this fix**, so no seeding decision was needed:
with alpha = 0.5, seed influence decays by half every bar and is fully gone within roughly 40
bars — since the shortest fetch window used anywhere in this app is still ~500 bars, seed choice
(first-value seed vs. an SMA seed vs. a shorter starting history) produced a measured difference
of exactly 0.0 across every real ticker checked.

### Price-basis sensitivity, checked and ruled out as a contributing factor

Before concluding the smoothing method was the entire gap, the investigation separately checked
whether Fathom's own price basis (FMP `full`: split- and spin-off-adjusted, not dividend-
adjusted) could itself explain any of the divergence. It doesn't, on the reference EMA
calculation: FMP's cached closes agreed with an independently-pulled split-only reference to
well under 0.02% across a full multi-year window, and a genuinely mixed-basis bug (raw High/Low
paired with a dividend-adjusted Close, the shape a partial future refactor could introduce by
accident) was confirmed to produce a *much* larger, clearly distinguishable error if it ever
happened — useful as a documented tripwire for a future change, since Fathom's own pipeline
already sources High/Low/Close from the same provider row in every code path and so never hits
this failure mode today.

### What shipped

1. **Switched smoothing to EMA** (alpha = 2/(n+1), recursive, `adjust=False`) in
   `compute_stochastic`, keeping the 5/3/3 period defaults unchanged (already the correct
   setting for this comparison). Removes the entire measured gap.
2. **Zero-range bars read %K = 0, not NaN** (ThinkOrSwim's own convention: `c2 != 0 ? c1/c2*100 :
   0`) — this matters specifically because pandas' `ewm()` silently *carries forward* the
   previous value across a NaN input rather than propagating it, so a NaN %K under EMA smoothing
   would have quietly masked a real zero-range bar instead of reading as the flat value it should.
   Zero occurrences of a zero-range bar were found in the real historical sample checked, so this
   had no visible effect on the numbers shown to date — it closes a latent correctness gap for
   whenever one does occur, not a bug that was actively firing.
3. **Label updated** to "Full Stochastic (5, 3, 3) EMA" so the chart itself states which
   smoothing convention is in use.
4. **The live/partial last bar is deliberately kept**, matching ThinkOrSwim's own behavior of
   showing the in-progress bar rather than waiting for it to close.

**Deferred, not shipped**: making K/slowing/D/smoothing-type configurable via Settings (the same
DB-backed pattern `LiquidityZoneConfig` already uses) — worth doing only if a future need arises
to match a *different* reference platform's own default settings (e.g. ThinkOrSwim's own script
default of 10/10/3 SIMPLE, rather than the user's actual 5/3/3 EXPONENTIAL setup this fix
targeted) or to let a user experiment; recommended as deferred rather than built speculatively.
Also deferred: dropping the same-day partial bar on the Chart path the way `SharedBarsCache`
does for its own nightly consumers — ThinkOrSwim itself shows the live/partial bar, so this may
not even be desired behavior; left as-is unless specifically asked for.

### Verification

Eye-checked by the user directly against real ThinkOrSwim/TradingView values for two tickers on
five real trading days each, both K and D — every value matched to the reported precision.
Confirmed without a browser via: a faithful from-scratch reference-EMA port cross-checked against
the shipped implementation; unit tests pinning the SMA-era values were updated to the new
EMA-era ones; and a direct comparison table of FastK/FullK/FullD across five real dates for two
tickers, checked against the user's own live platform reading.
