# Growth Rate

Technical reference for the Growth Rate check (the "Growth Rate" card on
the Analysis tab). Scores a company's forward analyst growth expectations
— a blend of projected growth magnitude and how tightly analysts agree on
the estimate.

## Data source

Sourced entirely from one provider's `/analyst-estimates` endpoint, which
aggregates individual analysts into an average, high, and low estimate per
future fiscal year. This is a single data source, not multiple independent
research platforms — the "agreement" metric below measures agreement
between analysts covering the stock, not agreement between different
research platforms.

Only forward-dated rows (estimate date after today) are used; past-dated
rows in the same response are discarded.

## Base and target year selection

- **Base row**: the nearest forward-dated estimate row (earliest future
  date in the response).
- **Target window**: rows dated 3–5 years after the base year.
- **Target row**: within that window, the row closest to **4 years** after
  the base year. If no rows fall in the 3–5yr window at all, every
  remaining forward row is used as the candidate pool instead.
- Within the candidate pool, rows with a usable (non-null, non-zero)
  average estimate are preferred over rows without one — FMP sometimes
  reports a `0` average for sparsely-covered far-out years even when a
  nearer year in the same pool has a real estimate, so a usable row is
  preferred over blindly taking whichever row sits closest to the 4-year
  center.

## Growth rate (CAGR)

```
growth_rate_pct = ((target_avg / base_avg) ^ (1 / years) − 1) × 100
```

where `years` is the whole-year gap between the base and target rows. This
requires `base_avg > 0`, a non-null/non-zero `target_avg`, and `years >
0`; if any of these don't hold, the CAGR is undefined for this field.

**EPS is preferred over Revenue.** The CAGR above is computed first using
EPS average estimates (`epsAvg`). If that doesn't yield a usable value —
most commonly because the base-year EPS is negative or zero, which makes
CAGR mathematically undefined — the same calculation is retried using
Revenue average estimates (`revenueAvg`) instead. Whichever field actually
produced a usable value determines the `basis` (`"eps"` or `"revenue"`)
reported alongside the score.

## Estimate agreement (spread)

For the same target year:

```
spread_pct = (high_estimate − low_estimate) / average_estimate × 100
```

using the high/low/average fields matching whichever basis (EPS or
Revenue) produced the growth rate. If the spread can't be computed, it
defaults to 100% (read as maximally wide/uncertain) for scoring purposes
only.

## Scoring

**Magnitude tiers** (on `growth_rate_pct`, half-open `[low, high)` so an
exact boundary value falls in the lower-numbered tier):

| Growth rate | Tier | Points |
|---|---|---|
| > 15% | strong | 100 |
| 10% – 15% | solid | 85 |
| 5% – 10% | modest | 65 |
| 0% – 5% | weak | 40 |
| < 0% | negative | 0 |

**Agreement tiers** (on `spread_pct`):

| Spread | Tier | Points |
|---|---|---|
| < 10% | tight | 100 |
| 10% – 20% | moderate | 60 |
| > 20% | wide | 20 |

**Blend**: `score = round(magnitude_points × 0.70 + agreement_points × 0.30)`,
clamped to [0, 100].

**Score floor**: whenever the magnitude tier is non-negative (i.e.
`growth_rate_pct ≥ 0`), the blended score is floored at **70** if it would
otherwise land lower. This raises only the displayed score for an
already-passing (non-negative-growth) result — it never changes the
magnitude/agreement component scores themselves, and it can never push a
score into Strong Pass range (the floor is 70; Strong Pass requires > 90).
A negative-growth (Fail) result is never floored — its real sub-70 score
displays as-is.

## Verdict

Deliberately **not** gated on the blended score, unlike every other
check's shared verdict logic:

- **Fail** if and only if the magnitude tier is `negative`
  (`growth_rate_pct < 0`) — regardless of the blended score. A weak-but-
  positive magnitude tier, even blended with maximally wide analyst
  disagreement, is never scored Fail.
- **Strong Pass** if the blended score is **> 90**.
- **Pass** otherwise (any non-negative growth rate that doesn't clear the
  Strong Pass bar).

## Insufficient data

If neither EPS nor Revenue yields a usable CAGR (too few or no forward
estimate rows, including a failed upstream data fetch, which is
indistinguishable from a genuinely thin response), the check returns
`score: null, verdict: "insufficient_data"` rather than a fabricated Fail.
