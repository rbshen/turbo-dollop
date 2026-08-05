# Growth Rate

The Growth Rate card looks forward rather than backward — it asks "how
much do analysts expect this company to grow over the next few years?"
It's built from two pieces:

- **Projected growth rate** — the expected annual growth rate between now
  and roughly four years out, based on analyst projections. Fathom
  prefers earnings-per-share (EPS) growth when it's usable, and falls back
  to revenue growth when EPS projections aren't usable (most often because
  the company's current earnings are negative, which makes an EPS growth
  rate mathematically meaningless).
- **Estimate agreement** — how tightly the individual analysts' estimates
  cluster around that average. If most analysts are projecting a similar
  number, that's read as higher-confidence; if the high and low estimates
  are far apart, that's read as genuine uncertainty about where the
  company is headed.

## Be aware: this is one data source, not several

Fathom's growth methodology was originally designed to average projections
across several independent research platforms and check whether they agree
with each other. In practice, Fathom sources this data from a single
provider's analyst-estimates feed, which itself aggregates many individual
analysts into one average, high, and low estimate. So "estimate agreement"
here means **how much individual analysts covering the stock agree with
each other**, not how much different research platforms agree with each
other. The app labels this explicitly wherever it's shown, so you always
know which comparison you're looking at.

## What the verdict means

Growth Rate has one deliberate difference from every other check in
Fathom: **a company is only marked Fail if its projected growth rate is
negative.** A modest-but-positive growth projection, even a fairly weak
one, is never scored as an outright Fail — the reasoning is that
weak-but-positive growth and genuine analyst disagreement shouldn't be
enough on their own to sink an otherwise-decent growth read. Scattered,
disagreeing estimates lower the score, but they don't flip a positive
growth projection into a Fail by themselves.

- **Fail** — analysts project the company will actually shrink (negative
  growth).
- **Pass** — analysts project positive growth, with the actual score
  reflecting both how strong that growth is and how much analysts agree
  on it.
- **Strong Pass** — a high score requires both a strong projected growth
  rate and tightly-clustered analyst estimates.

If there simply isn't enough analyst estimate data to compute a usable
growth rate for a company, Growth Rate reports **insufficient data**
rather than treating the gap as a Fail. See the [Glossary](glossary.md)
for how every verdict label is defined.
