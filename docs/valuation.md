# Valuation

The Valuation tab answers a different question than the Analysis tab: not
"is this a fundamentally sound business?" but **"is the stock currently
priced fairly, given what the business is worth?"** It estimates a fair
value per share and compares that against the stock's current price.

**Valuation is calculated completely separately from Overall Assessment
and is never blended into it.** A company can have a strong Overall
Assessment while its stock looks expensive, or a weak Overall Assessment
while its stock looks cheap — these are intentionally independent reads,
and the app never mixes them into one number.

## The fair-value method depends on the type of company

Fathom doesn't use one formula for every company — it picks an
appropriate valuation approach based on the kind of business and the
quality of its financial data:

- **Banks and REITs/Property Developers** are valued using a
  **Price-to-Book**-based approach — comparing the stock's price to the
  company's book (net asset) value, which is the standard way these
  asset-heavy, balance-sheet-driven businesses are typically valued,
  rather than a cash-flow projection.
- **Typical operating companies with strong, reliable cash generation**
  are valued by projecting their cash flow forward and discounting it back
  to a present value — a standard discounted-cash-flow-style approach.
  Fathom checks the quality of a company's cash flow first and prefers the
  most cash-based version of this approach it can reliably support,
  falling back to a profit-based version when cash flow itself isn't
  reliable enough for it (this is common for insurers in particular, whose
  cash flow is naturally lumpy due to claims timing and reserve
  movements, so they're valued on profit instead).
- **Unprofitable but fast-growing companies**, where neither a cash-flow
  nor a profit-based method has anything usable to project, are valued off
  their sales growth trajectory instead.
- If none of these approaches has enough usable data to apply, Valuation
  reports that no method currently applies, rather than forcing an
  estimate from insufficient data.

## Reading the result

Once a fair value per share is calculated, Fathom compares it to the
stock's live price and labels the result **Undervalued**, **Fair
Valued**, or **Overvalued**. Undervalued means the current price sits
meaningfully below the calculated fair value (a potentially attractive
entry point, by this measure); Overvalued means the reverse; Fair Valued
means the price is roughly in line with the estimate.

## The Manual Calculation panel doesn't save

Below the automatic result, a **Manual Calculation** panel lets you
override the underlying inputs — growth rate assumptions, discount rate,
and similar — to see how the fair value estimate changes under different
assumptions. This is a what-if tool only: **any changes you make here are
not saved anywhere and reset the moment you leave the page.** It's meant
for exploring "what if growth were faster/slower" in the moment, not for
recording an alternate valuation.
