# Profitability

The Profitability card asks how efficiently a company turns the capital
invested in it into profit, and whether its day-to-day operations are
run efficiently. It looks at up to four things, depending on the company:

- **Return on Equity (ROE)** — how much profit the company generates for
  every dollar shareholders have invested in it. A consistently strong ROE
  suggests the business is a genuinely efficient user of shareholders'
  money.
- **Return on Invested Capital (ROIC)** — a broader version of the same
  idea, measuring profit generated against *all* the capital in the
  business (both shareholder equity and borrowed money), not just the
  equity portion. ROIC is harder to artificially inflate than ROE, since
  ROE alone can be flattered by taking on debt to fund share buybacks —
  Fathom weighs ROIC slightly more heavily than ROE for this reason, and
  will flag it as a note (not a score penalty) when ROE looks notably
  stronger than ROIC.
- **Accounts Receivable trend** — whether the money customers owe the
  company (but haven't paid yet) is growing faster than revenue itself.
  When receivables consistently outpace revenue, it can mean the company
  is recognizing sales before it's actually collecting cash for them —
  worth a closer look, though not automatically a sign of trouble.
- **Cash Conversion Cycle (CCC)** — roughly, how many days it takes the
  company to turn money spent running the business back into cash from
  customers. A shorter cycle is more efficient. A CCC that's actually
  *negative* is not a milder version of a positive one — it's the
  opposite, and better, signal: it means the company collects cash from
  customers before it has to pay its own suppliers, so suppliers are
  effectively financing the business's day-to-day operations. Fathom
  treats a consistently negative CCC as a top-tier result, not a warning
  sign.

## A weak result on ROE or ROIC always fails the whole card

Revenue-vs-Receivables and CCC are treated as supporting evidence for what
ROE and ROIC already indicate, not independent headline signals. If either
ROE or ROIC (when applicable) comes in genuinely weak, the whole
Profitability check fails outright, regardless of how the other two
metrics look — a strong receivables or cash-cycle trend can't rescue a
fundamentally weak return on capital.

ROE and ROIC are judged on multiple years, not a single snapshot — but a
rough patch that's genuinely behind the company (a real, multi-year rough
stretch that's since given way to a sustained, durable recovery) doesn't
keep dragging the reading down forever once it's clearly over, the same
way a temporary dip is tolerated elsewhere in this app's checks. This cuts
both ways: it's also possible for a company whose best years are behind
it, with a real rough stretch still ongoing today, to read weaker once
those old strong years stop counting — a currently-declining business
isn't rescued just because it once performed well.

## Some checks don't apply to every company type

- **ROIC** isn't meaningful for Banks, Insurance companies, Utilities, or
  REITs/Property Developers, and is skipped for those company types.
- **Cash Conversion Cycle** isn't meaningful for the same set of company
  types, and is also automatically skipped for any company that carries no
  physical inventory at all (e.g. many software and services businesses),
  since the underlying concept doesn't apply cleanly to a business that
  doesn't stock goods.
- **Accounts Receivable trend** isn't meaningful for Banks, Insurance
  companies, Utilities, or REITs/Property Developers either — REITs
  (rental income) have no comparable concept of receivables outpacing
  revenue, and Bank/Insurance/Utility revenue recognition doesn't map onto
  ordinary trade receivables the way a Standard operating company's does.

When a check is skipped, the remaining applicable checks are reweighted
to make up the difference, rather than penalizing the company for a metric
that doesn't apply to its business model. See
[Company type variations](company-type-variations.md) for the full
picture.

## What the verdict means

- **Fail** — ROE, or ROIC where applicable, comes in weak, regardless of
  how the other metrics look.
- **Pass** — returns on capital are solid overall.
- **Strong Pass** — returns on capital are excellent, with supporting
  metrics (receivables trend, cash cycle) also reading well.

See the [Glossary](glossary.md) for how every verdict label is defined.
