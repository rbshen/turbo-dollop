# Economic Moat

Economic Moat is the simplest input in Fathom, and the only one that isn't
computed from financial data at all: it's a rating **you set yourself**,
based on your own judgment of whether the company has a durable
competitive advantage — something that protects its profits from
competitors over the long run (a strong brand, network effects, high
switching costs, patents, scale advantages, and similar).

## The three ratings

You choose one of three states from the Economic Moat tab:

- **No Moat** — no meaningful, durable competitive advantage protecting
  this business from competitors.
- **Narrow Moat** — some real advantage exists, but it isn't strong or
  broad enough to reliably fend off competition indefinitely.
- **Wide Moat** — a strong, durable advantage expected to hold up for a
  decade or more.

There's no built-in checklist or scoring rubric behind these — Fathom
doesn't attempt to compute a moat rating from financial data, and doesn't
offer any automated suggestion for which one to pick. It's entirely your
own qualitative assessment of the business.

## Why it matters this much

Once you set a rating for a ticker, it's folded into the Overall
Assessment at a 31% weight — the single largest weight of any component,
larger than any one of the four automated financial checks on its own
(see [Overview](overview.md) for the full weighting). This is a deliberate
design choice: a durable competitive advantage is treated as at least as
important to a company's long-term investment case as any one quarter's
worth of financial performance.

Until you set a rating, Overall Assessment simply reports the blend of the
four automated checks on their own — leaving Moat unrated doesn't drag the
score down or count against the company. It's only once you actively
select **No Moat** that it becomes a real, negative input pulling the
blended score down; the unrated state and "No Moat" are not the same
thing.

## It doesn't persist automatically until you confirm it

Changing the selector shows you a live preview of the new rating, but
nothing is saved until you explicitly confirm the change — since doing so
changes how Overall Assessment is scored for that ticker. You'll see a
prompt asking you to confirm before it takes effect.
