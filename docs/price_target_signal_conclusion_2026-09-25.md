# Price-vs-analyst-target gap: is it a viable signal? -- conclusion, 2026-09-25

Investigation only. No production code, schema, crontab or data was changed. The only external I/O was
577 read-only, un-persisted `GET /price-target-news` reads (plain `httpx`, paginated, 0 failures) and
read-only (`mode=ro`) queries against `backend/fathom.db`. Scratch scripts and pickles were deleted.
Follows `price_target_trend_signal_investigation_2026-09-22.md` (the exploratory pass this replaces as the
reference) and `price_target_trend_sept_gap_investigation_2026-09-25.md` (the legacy/live methodology split).

## Verdict: SHELVE. Do not build a card, alert or score input on this.

Not "needs more data". The out-of-sample test was adequately powered to see a moderate effect and found none
(section 6), the 2026-09-22 result that looked like a signal is reproduced here but shown to be a
time-series artifact that a price-only placebo beats (section 5), and the one tail bucket that looked
interesting turned out to be contaminated by split-basis errors and vanishes once they are removed
(section 4). More live months would tighten the interval slightly but would not change the decision.

The result in one line: **the monthly cross-sectional rank correlation between (price - target)/target and the
next 21-day SPY-relative return is -0.012 out of sample (t = -0.41, 30 months), with a 95% interval of about
[-0.07, +0.05]. The long-short spread (lowest-gap quintile minus highest) is +0.2%/month (t = +0.24).**

## 1. Signal definition (fixed before looking at any out-of-sample month)

- **Gap**: `gap_t = close_t / avg_target_t - 1`. Positive = price above the analyst average target.
  Hypothesis under test: a high gap predicts underperformance, a low gap predicts outperformance.
- **Target series** (two, both rebuilt from raw per-analyst `price-target-news` actions, split-adjusted via
  `adjPriceTarget`, using only actions published before the month-end):
  - **A ("legacy")**: latest target per analyst, mean over every analyst who has ever issued one. This is exactly
    what the stored `legacy_all_analysts` rows hold.
  - **B ("live-like")**: latest target per analyst, mean over analysts whose latest action is <= 180 days old.
- **Entry / horizon**: signal read at month-end `t`; entry at the **next trading day's close** (conservative, the
  signal needs `t`'s close); exit 21 trading days later (primary) or 63 (secondary). Return measured **in excess
  of SPY over the identical window**. SPY-relative removes the market; the stock's own baseline is handled in
  section 5.
- **Statistics**: per month, cross-sectional Spearman IC of gap vs forward excess return; quintile spread
  (lowest-gap minus highest-gap quintile); fixed gap bands. Significance is a t-stat over the monthly series
  (non-overlapping at 21d), which respects cross-sectional correlation within a month.
- **Not modelled**: costs, sizing, borrow, dividends (price return on both legs).

## 2. Sample construction

**Universe**: the 577 tickers with snapshot rows (566 legacy + live-only extras), i.e. today's tracked names.
Months: 2021-10 through 2026-07 (last month with a full 21d forward window; price bars begin 2021-09-27).

**Freshness (item 3).** Every stored legacy row was checked against the raw actions:
- My reconstruction reproduces **all 32,764 stored `legacy_all_analysts` rows exactly** (<0.1% difference on
  100%), so the raw feed and the table agree.
- A ticker-month is **fresh** if at least one analyst action was published in that calendar month (A_fresh), or,
  for B, at least one in the trailing 30 days plus >= 3 analysts inside the 180d window (B_fresh). Forward-filled
  months are excluded from the headline tests and reported separately (A_stale) as a contrast.
- **Only 47% of legacy ticker-months are fresh** (2021 50%, 2022 53%, **2023 20%**, 2024 50%, 2025 45%, 2026 73%),
  which matches the "~56% forward-filled" caveat from 09-22.

**A data-density problem found on the way (new).** FMP's `price-target-news` log is very uneven across the whole
universe: ~120-190 recorded actions per month from Mar 2023 to Feb 2024, against 1,000-2,500 per month in
2024-04..10 and 2025-10 onward. A 500-name large-cap universe realistically generates well over 1,000 a month, so the
sparse stretch is a **hole in the feed, not analyst quiet**. Consequences: in those months "no action" is not
evidence the target was still current, and the freshness filter is what keeps them out (2023 retains only ~20% of
rows). The reconstruction is faithful to the feed but the feed itself is thin before 2024-04.

**Exclusions** (rows / tickers): delisted or stitched (AVB, EA, EQR, SPCX, TWTR, WBA; 243 ticker-months);
ticker-quarters whose median `adjPT / price` at posting fell outside [0.4, 2.5], i.e. split-basis defects (283
ticker-months, 23 tickers: ANET, APH, B, CELH, COO, CSX, CTAS, CVNA, DD, DECK, DXCM, EXPD, HOOD, IBKR, IONQ, IREN,
MNST, NFLX, OMC, ORLY, PANW, SEZL, TSCO). Not excluded: the >60% one-day-jump names (MRNA, SOUN, ASTS...): those
are real volatility, and dropping them would remove the tail being tested. Result: 31,395 usable ticker-months,
~520 per month.

**Contamination check (item 2).** Including the delisted/stitched rows changes the headline IC from -0.0120 to
-0.0124: immaterial. The basis-defect tickers matter a great deal for the *tail* (section 4), not for the pooled IC.

## 3. Validation that B is what live consensus actually is

At 2026-09-25 (the only date with live rows) a 180-day latest-per-analyst mean reproduces FMP's live
`/price-target-consensus` **within 1% for 97.9% of 565 tickers (median error 0.0%)**. 90d and 365d windows do not
(38% / 28% within 1%). This extends the 09-25 gap investigation (3 hand-checked tickers) to the whole universe and
means the B history is a legitimate stand-in for the definition a live feature would use.

## 4. Results

**Split (fixed in advance)**: in-sample (IS) 2021-10..2023-12 (27 months); one-month embargo; out-of-sample (OOS)
**2024-02..2026-07, 30 months** with a 21d window (28 with 63d). IS was used only to choose between two forms of
the signal (raw gap; gap divided by trailing 60-day volatility). IS gave no basis to prefer either (every IC within
+/-0.03, all |t| < 1.3), so **both were carried to OOS unselected and no threshold was tuned**. OOS was run once.

OOS, mean monthly IC of gap vs SPY-excess return (expected sign: negative), and Q1-Q5 spread (lowest minus highest
gap quintile; expected positive):

| Sample | Rows | IC 21d | IC 63d* | Q1-Q5 21d/month |
|---|---|---|---|---|
| A_fresh, raw gap | 8,806 | +0.017 (t +0.52) | -0.001 (t -0.05) | -0.6% (t -0.57) |
| A_fresh, vol-scaled | 8,806 | +0.020 (t +0.61) | +0.005 (t +0.23) | -0.8% (t -0.89) |
| A_stale (forward-filled, contrast) | 7,425 | -0.024 (t -0.88) | -0.013 (t -0.73) | +0.6% (t +0.59) |
| **B_fresh, raw gap** | 7,929 | **-0.012 (t -0.41)** | -0.047 (t -1.72) | +0.2% (t +0.24) |
| B_fresh, vol-scaled | 7,929 | +0.009 (t +0.30) | -0.016 (t -0.64) | -0.7% (t -0.82) |
| B_all (incl. non-fresh) | 12,110 | -0.015 (t -0.59) | -0.037 (t -1.48) | +0.2% (t +0.31) |

\* 63d windows are sampled monthly and therefore overlap ~3x, so their t-stats are overstated by roughly sqrt(3).
The 63d B_fresh figure (t -1.72 nominal, ~-1.0 adjusted) is the closest thing to a signal in the table; it is
nowhere near significant once the ~30 cells examined and the overlap are accounted for, and the same variant was
**wrong-signed in-sample** (+0.028), so it does not replicate across periods.

Fixed-band view (what an alert would actually be), OOS, B_fresh, excess return relative to the same-month
universe average, **after dropping the 23 basis-defect tickers**:

| Band | Obs | Months | Rel. return (21d) | t | Note |
|---|---|---|---|---|---|
| gap < -40% (price far below target) | 142 | 26 | +1.1% | +0.47 | 95% bootstrap [-3.2%, +5.5%] |
| gap < -30% | 511 | 30 | +0.4% | +0.37 | |
| gap > +30% (price far above target) | 75 | 20 | +9.9% | +1.73 | drops to +3.7% without the 2 largest months; **wrong sign** for reversal |
| gap > +40% | 55 | 19 | +4.9% | +1.31 | wrong sign |

Before removing the basis-defect tickers the <-40% bucket read **+6.0% (t +2.4)** on B_fresh. That was an artifact:
MNST, APH, PANW and CELH alone supplied ~22% of its observations (their split-adjusted targets sit on a different
basis in other quarters, manufacturing a large negative "gap"), and two months (Oct-2024 +26%, Apr-2025 +17%) carried
the mean. It is recorded here because it is exactly the kind of number that would have justified a build.
The high-gap tail, if anything, shows continuation rather than reversal, but it is 55-75 observations and not
robust; it is also the direction survivorship would inflate (section 8).

## 5. Does it survive the stock's own baseline? (item 5)

- **Fama-MacBeth, OOS, standardized ranks**, B_fresh: gap coefficient -0.012 (t -0.41) alone, -0.004 (t -0.14) after
  controlling for trailing 1-month return and 60-day volatility, -0.024 (t -1.15) after adding 12-1 momentum.
  A_fresh: +0.017 / +0.030 / +0.008, all |t| < 1. There is no gap effect to survive controls: the point estimates
  are noise around zero. (The trailing 1-month return coefficient itself is +0.035 to +0.047, t ~1.3-1.8: no
  short-term reversal either in this large-cap sample.)
- **The 2026-09-22 finding, reproduced and explained.** That pass found a per-ticker time-series correlation of
  gap vs next-month return of about -0.23 (90% of tickers negative) and called it "meaningfully stronger than naive
  reversion". Re-running that statistic on this panel gives -0.147 (A_all; 87% of tickers negative), -0.122
  (A_fresh) and -0.101 (B_fresh): the effect replicates. But a **placebo with no analyst input at all**
  (price relative to the ticker's own average, correlated with next-month return) gives **-0.183 (93% negative)**,
  stronger than any target-based version. The old comparison baseline was one-month return autocorrelation, which
  does not contain a price-level term. What the old statistic measures is per-ticker, in-sample mean reversion of
  the price *level* (with the usual finite-sample downward bias in level-vs-future-return regressions), which any
  price-vs-average measure would show. It is not target information. In the cross-section, where a tradeable
  signal has to live, it is absent.

## 6. Statistical power and significance (item 5)

- OOS sample: 30 months, ~264 fresh names per month on average (7,929 rows, 559 tickers) for B_fresh.
- Monthly IC standard deviation 0.160 -> standard error 0.029. **Minimum detectable mean IC at 80% power (5% two-sided)
  is ~0.08.** For the quintile spread the standard error is 0.81%/month, so the minimum detectable spread is
  ~2.3%/month (~27% annualized, before costs).
- Reading: the test **rules out anything approaching a strong signal** but cannot exclude a small one (a true IC of
  0.02-0.03 would be invisible). Effects that small are typical noise-level for a 21-day horizon and would not
  survive costs or justify a feature; the observed point estimates are also on both sides of zero depending on the
  variant, which is what noise looks like.
- Multiplicity: the OOS table has ~30 cells and the band table more; one cell at |t| ~1.7 is expected by chance.

## 7. Live `live_consensus` data: is it usable yet? (item 6)

**No, and the conclusion does not depend on it.** The table holds 574 live rows: 2 (AAPL, MSFT, 2026-07-27, from a
manual test) and 572 tickers on **2026-09-25** (the server date, not the 09-26 the brief assumed: the first full
run happened on 09-25). That is **one cross-section, no forward returns observable, effectively zero months of
test data**. Everything above rests on the reconstructed history. That is defensible only because section 3
shows the B reconstruction reproduces the live definition (97.9% within 1%), but the reconstruction inherits the
feed's historical sparsity (section 2), so historical readings can differ from what live FMP would have shown at
the time if the feed omitted analyst actions.

## 8. Limitations, stated plainly

1. **Survivorship (item 2), not fixable here.** The universe is today's tracked names projected backward; companies
   that failed, were acquired or dropped out of the index since 2021 are absent, and current index members were
   partly admitted *because* they rose. This favors observed continuation in the high-gap (winner) tail and hides
   losers from the low-gap tail (which would flatter a buy-the-discount signal). Only 6 delisted/stitched tickers
   existed in the tracked set and they were immaterial; the true bias cannot be sized from this DB.
2. **Short, one-regime OOS**: 30 months, mostly a rising market, one large drawdown (Apr 2025). Regime changes are
   untested.
3. **Feed sparsity** before 2024-04 (section 2): the IS period is mostly the sparse-feed period, so IS is weaker
   evidence than its row count suggests; OOS is the better-populated one.
4. **Price basis**: prices are FMP `full` (split- and spin-off-adjusted); targets are FMP's `adjPriceTarget`.
   Basis defects were screened by ticker-quarter and the 23 worst tickers dropped, but some residual basis error
   inside the kept sample is possible. Excluding the ~18 known spin-off names, or |gap| > 150%, or sub-$10 stocks,
   or requiring >= 5 analysts, moved no headline result (IC21 -0.012 to -0.016).
5. No costs, no sizing, price return only (dividends omitted on both stock and SPY legs).
6. IS was not used for tuning beyond the (uninformative) form comparison; OOS was evaluated once, but the
   tail-contamination follow-up in section 4 was a post-hoc diagnostic after seeing that bucket, and is labeled as such.
7. The prior finding that "price leads target" (targets are reactive) was not re-tested here; it is not needed for
   this verdict.

## 9. Verdict and reasoning

**Shelve as a predictive signal.**

- *Build a card / alert / score input?* No. There is no out-of-sample edge (IC -0.012, t -0.41; spread +0.2%/month),
  it does not change with controls, the apparent tail effect was a data-basis artifact, and the earlier positive
  finding was a mechanical time-series effect that a price-only placebo beats.
- *Needs more data?* No. The design could see an IC of ~0.08, so a moderate effect is excluded; the residual
  question is whether a true effect of ~0.02-0.03 exists, which would not be worth a feature even if confirmed.
  Twelve more months of live data (~+40% sample) would move the detectable IC from ~0.08 to ~0.07.
- *What survives:* the descriptive Analyst Ratings display (price vs target as context, the legacy-vs-live
  methodology note) is a separate product question and is unaffected. It should not be labeled predictive.
- *What would reopen it:* a genuinely different hypothesis (e.g. target *revisions* or dispersion rather than the
  price-vs-average gap), or a survivorship-free universe. Neither is implied by these results. If someone does
  revisit, the fresh-only, SPY-relative, pre-split protocol above is the one to reuse, and the FMP action-log density
  and the split-basis screen must be repeated first, since both materially changed the answer here.
