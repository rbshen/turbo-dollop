# How Fathom scores a company

Fathom runs a fundamentals screen on any US-listed ticker. When you open a ticker page, you'll
see several tabs: **Summary**, **Financials**, **Ratios**, **Analysis**, **Valuation**,
**Economic Moat**, **Analyst Ratings**, and **Technical**. This overview explains how the
**Analysis** tab's score is built and how it relates to the **Valuation** tab, which is
calculated completely separately.

## The Analysis tab: Overall Assessment

The Analysis tab blends four automated checks into a **Fundamentals score**, then applies the manual **Economic Moat** rating as a
**multiplier** to give the **Overall Assessment** (redesign of 2026-10-07; docs/decisions.md):

**Overall = Fundamentals score x Moat multiplier**

| Card | What it checks |
|---|---|
| **Financials** | Revenue, Net Income, Cash From Operations, Margins, and Free Cash Flow (Banks, Insurance, REITs and Commodity companies: Revenue and Net Income only) — see [Financials](financials.md) |
| **Growth Rate** | Forward analyst growth expectations — see [Growth Rate](growth-rate.md) |
| **Profitability** | Return on Equity, Return on Invested Capital, Accounts Receivable trend, and Cash Conversion Cycle — see [Profitability](profitability.md) |
| **Debt** | Short-term liquidity, leverage, and debt service burden — see [Debt](debt.md) |
| **Economic Moat** | A manual, judgment-based competitive-advantage rating you set yourself — a multiplier, not a blend component; see [Economic Moat](economic-moat.md) |

Each of the four automated cards produces its own score (0–100) and verdict (Fail, displayed "May not pass" / Pass /
Strong Pass; the Debt card alone can also read "Pass, ratio in breach", the display word for its stored `Pass with caution` — see the
[Glossary](glossary.md)). The **Overall** verdict has the same words (Strong Pass, Pass, Pass with caution, May not pass) under the rule in
"The Overall verdict" below; **"Pass with caution" means the Overall verdict only** (decision 2026-10-08, "two meanings").

**The Fundamentals score** is the weighted average of the four checks, rescaled to 100 over the checks that apply to the company. These are
the **default** weights; all four are adjustable in Settings > Score weighting (see "Adjustable weights" below) and must add up to 100:

| Component | Default weight |
|---|---|
| Financials | 30% |
| Debt | 30% |
| Growth Rate | 20% |
| Profitability | 20% |

These are the defaults in the code (`scoring/weights.py::DEFAULT_WEIGHTS`). The weights actually in force are the **saved** set, which can differ: on
2026-10-08 the live database held Financials 35 / Growth 20 / Profitability 20 / Debt 25 (Step 1 30/20/25/10/15, Step 2 80/20). Settings > Score weighting shows what
is in force; every percentage derived from a weight in these specs (for example the exempt-type tables) is quoted at the defaults.

**The Moat multiplier** scales the finished Fundamentals score:

| Moat rating | Multiplier |
|---|---|
| Wide Moat | 1.0 (fixed) |
| Narrow Moat | 0.85 by default; one of 0.80, 0.82, 0.85, 0.87, 0.90, set in Settings > Economic moat |
| No Moat, or **not rated** | 0.70 (fixed, not editable) |

A ticker with no Moat rating is **scored as No moat**: there is no separate "Moat not rated" verdict (retired 2026-10-07). Its verdict is
read from its Overall score like any other, and the Analysis card and the ticker header show the note "Moat not rated, scored as No
moat". Because 0.70 x a perfect Fundamentals score of 100 is exactly 70, a No moat or unrated ticker can reach the Pass line only with four
perfect check scores, which does not happen in practice (the verification after the 2026-10-07 recompute is in docs/decisions.md).

**Worked example.** Financials 84, Growth Rate 84, Profitability 83 and Debt 84 give a Fundamentals score of
0.30 x 84 + 0.20 x 84 + 0.20 x 83 + 0.30 x 84 = 83.8; for a Narrow Moat ticker at 0.85 that is 83.8 x 0.85 = 71.23, an Overall score of
**71**. The Analysis card shows exactly this arithmetic, **collapsed by default** (state not persisted) to the one line "Fundamentals 83.8 x Narrow moat 0.85 = 71" with a
"Show calculation" toggle; expanded it shows a table of each step with its score, weight and points, then the Fundamentals score (one decimal), the result line, and the
explanatory paragraph with its links. The Score cells in the table are coloured with the same green / amber / slate (May not pass) tones the step pills used (the pills under
the header were removed 2026-10-07); weights, points and the Fundamentals score are not. The score circle, the verdict, the "N of 4 weighted components" line and the
failing / caution warning lines stay outside the collapsible and are always visible.

**Rounding (decision 2026-10-07).** The Fundamentals score is computed unrounded, multiplied, and the Overall score is rounded **once**, with
Python `round` (half to even; the app's convention). The Fundamentals score is stored unrounded and shown to one decimal. Rounding the Fundamentals
score first would sometimes change a verdict (Fundamentals 81.6 x 0.85 = 69.36 reads 69, a Fail; 82 x 0.85 = 69.7 would read 70, a Pass).

The Overall verdict bands are the shared ones used app-wide: Fail below 70, Pass 70-90, Strong Pass above 90. On top of the band,
**Pass with caution** (decision 2026-10-08, `scoring/overall.py::compute_overall_assessment`, mirrored in `frontend/lib/overallScore.ts`):
a Pass or Strong Pass reads "Pass with caution" when **either** a check carries its own stored `Pass with caution` (today only Debt, drawn
"Pass, ratio in breach" on its own card, see [Debt](debt.md)) **or** at least one of Financials, Growth Rate, Profitability or Debt is below the pass line (score under 70 or a stored `Fail`
verdict: "May not pass"). The two reasons combine (`caution_reasons` lists `step_caution` and/or `weak_step`; `caution_steps` and `weak_steps` name
the steps). An exempt check (`not_supported`, such as Insurance Debt) is never weak, an incomplete row has no verdict, an Overall under 70 stays
"May not pass" (stored `Fail`), and Moat plays no part. It changes only the label: the Overall score, `steps_score`, the sort, the step score range
filters and `SCORE_FORMULA_VERSION` are untouched (stored rows were refreshed by a full recompute instead of a version bump). The Analysis card
adds an amber line naming the cause in plain words ("Pass with caution, because Financials may not pass — ... under 70", beside the Debt line "Pass with caution, because Debt passed with a ratio in breach — ..."; the Debt line drops the "Pass with caution, because" start when the Overall is not a Pass with caution); on a Pass with caution the
slate "X may not pass" failing-steps line is hidden, since the amber line already names those steps (it still shows on "May not pass"). Step lists read "A, B and C".
The Watchlist Analysis tooltip names both kinds in the same words ("Pass with caution, because Debt passed with a ratio in breach and Growth Rate may not pass (under 70)").
There is **no cap and no
hard-fail override**: a hard fail inside a check (Step 4 negative average ROE or ROIC) still reads Fail on that check's own card and
still enters the blend only through its score. Step 5 has no hard fail on any path (Standard and Utility since 2026-10-07, Bank and REIT
since 2026-10-08): the verdict follows the score and 70 or more passes ([Debt](debt.md)).
Since 2026-10-08 the stored verdict `Fail` is displayed as **"May not pass"** on every surface, every step and the Overall verdict
(display only: the stored key, the API and every comparison are unchanged; a slate blue tone, not red, and a plain 70-74 Pass is green, no longer amber;
docs/design-system.md, "Pills"). The Economic Moat is no longer the one
exception that can pull Overall below 70 by itself: the multiplier is the whole mechanism (a No moat or unrated ticker needs Fundamentals of 100
to reach 70).

The defaults reflect two deliberate design choices. Financials and Debt carry the most weight: Financials is the most foundational
read on the business, and Debt is weighted equally with it (originally lifted above Growth Rate in the 2026-07-31 rebalance, so that a genuine
debt problem can't be fully diluted away by strength elsewhere; see [Debt](debt.md), and
docs/archive/claude-md-history-scoring.md for that investigation). And a durable competitive advantage still matters at least as much as
any single financial metric, but it now acts on the whole result rather than as one 31% slice: a Narrow Moat costs 15% of the Fundamentals
score by default, a missing or No Moat costs 30%.

**Saved Screener views and the weights.** A saved view stores filters (the Overall verdict set `overallVerdicts` and the Financials / Growth /
Profitability / Debt score ranges, among others) and a sort, never results. Changing
the weights or the Narrow multiplier re-scores every ticker, so the same saved view then selects different tickers; nothing in the view
itself changes. The 2026-10-07 formula change moved scores too (see docs/decisions.md), so a saved score range selects different
tickers than before. Saved views written before 2026-10-08 stored an Overall score range (`overallScore`); a one-time migration turned it
into a verdict set (min 70 → Strong Pass + Pass + Pass with caution, 91+ → Strong Pass, a max under 70 → May not pass), and the Screener's
loader keeps only the keys the filter state has, so a leftover `overallScore` or `reviewStatuses` is neither applied nor written back.

The default weights are defined once, in `backend/scoring/weights.py::DEFAULT_WEIGHTS` (every scorer takes a weight set as a
parameter and defaults to it; `overall.py::STEP_WEIGHTS` is just the Overall defaults as fractions of 100). The multipliers are
constants in `scoring/overall.py` (`WIDE_MOAT_MULTIPLIER`, `NO_MOAT_MULTIPLIER`, `NARROW_MOAT_MULTIPLIER_OPTIONS`,
`DEFAULT_NARROW_MOAT_MULTIPLIER`); the saved Narrow value lives in `MoatScoreConfig`. The frontend mirror
`frontend/lib/overallScore.ts` has no weight constants: `computeOverallAssessment` takes the saved set and the Narrow multiplier as
arguments (hooks `useScoreWeights`, `useMoatConfig`), and both implementations are tested against one shared case file,
`backend/tests/fixtures/overall_verdict_cases.json` (curated cases, every Narrow option, exact-.5 rounding cases, and 150 random weight
sets generated by the backend: `backend/tests/fixtures/generate_overall_verdict_cases.py`).

**Rounding detail.** The backend uses Python `round` (half to even). The TypeScript mirror matches it exactly: `lib/pyNumeric.ts::roundHalfEven`
(JavaScript's `Math.round` sends 42.5 to 43, Python gives 42) and `pySum`, Python 3.12's compensated float `sum` (a plain left-to-right
sum differs in the last bit for about a quarter of 4-term blends). The blend also runs in the fixed step order Financials, Growth,
Profitability, Debt whatever order the caller lists the steps.

## Adjustable weights: storage, bounds and API (2026-10-06; Overall set rescaled to 100 on 2026-10-07)

The weights are one global set (no accounts, no per-user weights) saved in the database (`ScoreWeightSettings`, a lazily seeded singleton; `weights_version` goes up by
one on every save or reset **and on every save of the Narrow moat multiplier**, and `TickerScore.weights_version` records the version a row was scored with).
Definitions, defaults, bounds and the pure derivations are in `backend/scoring/weights.py`; loading, the 5-second in-process cache and saving are in
`backend/data/score_weights.py`. A read never writes (an unseeded database serves the defaults at version 1). Economic Moat is not a weight and is not part of
the set; its multipliers are `scoring/overall.py` constants plus the one saved Narrow setting.

Whole numbers only. The four Overall weights add up to **100** and each step's own set to 100. Bounds, inclusive: Overall Financials
10-50, Growth 5-50, Profitability 5-50, Debt 10-50 (a floor of 10 keeps the foundation and the bankruptcy filter from being diluted away; no
step may exceed half of the Fundamentals score; before 2026-10-07 the cap was 30 so that Moat's 31 stayed the largest weight, a tie that no longer
exists); Step 1 Revenue 20-50, Net Income 10-40, CFO 10-40, Margins 0-25, FCF 0-15; Step 2
Magnitude 50-100, Agreement 0-50; Step 4 ROE 15-60, ROIC 15-60, AR 0-30, CCC 0-30; Step 5 Debt/EBITDA 35-60, Debt Servicing 15-30, Current Ratio 15-30 (default Current Ratio 25 / Debt/EBITDA 45 / Debt Servicing 30), and Step 5 must
keep the strict order Debt/EBITDA > Debt Servicing > Current Ratio (the one ordering rule; `scoring/weights.py::ORDERINGS`, enforced in `validate_group`
and in the Settings form, 422 on `PUT`): with no hard fail the weights alone keep a Debt/EBITDA breach below 70 ([Debt](debt.md), "Weights and bounds").

**Migration (2026-10-07).** The Overall set used to add up to 69 (Moat was the other 31). `core/db.py::_migrate_moat_and_overall_weights`
runs once at startup: a saved set still adding up to 69 is converted. The old defaults (24/10/20/15) become the new defaults
(Financials 30, Growth 20, Profitability 20, Debt 30); a customised set is rescaled proportionally to 100 with largest-remainder rounding
(`scoring/weights.py::rescale_overall_to_100`) and logged as a warning; either way `weights_version` goes up by one. A set already
adding up to 100 is left alone, so the migration is idempotent and writes nothing once done.

**Step 5 migration (2026-10-07).** `core/db.py::_migrate_step5_weights` runs right after it: a saved Step 5 set that breaks the new bounds or the strict
order (the old default 33/33/34 does) is replaced by the new defaults and `weights_version` goes up by one (logged as a warning); a customised set that
still satisfies the rules is left alone. Until it has run, `data/score_weights.py` serves the default Step 5 set for such a row, so a cron job or the
recompute subprocess can never score with weights that would let a breach pass.

`GET /api/config/score-weights` returns the weights, the defaults, the bounds and sums, `weights_version` and `formula_version`;
`PUT` saves a full set (422 with a plain-English reason naming the set and the rule); `POST /api/config/score-weights/reset`
restores the defaults. A weight of 0 removes a component from the blend only: a missing input can still make the step insufficient,
and a hard fail (Step 4) still reads Fail. Step 2 has none (its verdict follows its score). Saving does not rescore anything by itself; the stored rows stay on the older version until a full
recompute (`compute_ticker_score`) re-scores them, and a ticker-header read of a row on an older version re-scores it (cache only).

**Formula version.** `weights_version` cannot see a change of *formula*, so every stored row also carries `TickerScore.formula_version`
(`scoring/overall.py::SCORE_FORMULA_VERSION`; 1 = the old 69/31 blend, which rows never stored, so NULL; 2 = Fundamentals x multiplier; 3 = the neutral Step 1 engine; 4 = its age-decayed dip costs; 5 = Step 5 without its hard fail, 25/45/30; 6 = the Step 1 Commodity exemption by industry allowlist). A row
whose formula version is not the current one is stale: the ticker header re-scores it (cache only, whatever its weights version), and the
Screener's "N scores are still on the previous weights" note counts it. Bump the constant whenever the Overall arithmetic changes.

### Applying a change: the recompute job

Every change that moves stored scores (saving or resetting the weights, **saving the Narrow moat multiplier**, the Screener's "Recompute all scores")
goes through the full `compute_ticker_score` path as one **background job** (`data/score_recompute.py`,
`pipeline/score_recompute_job.py`), never a SQL re-blend: the Overall verdict and every step score depend on
the weights. It runs in a subprocess so it cannot block the API, one run at a time (a second request is a 409 and is not
queued), with a status row (`ScoreRecomputeRun`) the Settings page polls. The change is saved first, then the job starts, so it always
scores with the new values. Until the job reaches a ticker its stored row keeps the old `weights_version`. Operations: OPS_RUNBOOK,
"Score recompute job".

## Overall weighting: how the weights are stored, and the 2026-07-31 rebalance

In code the four automated steps are stored as fractions of their total:
`STEP_WEIGHTS = {"step1": 30/100, "step2": 20/100, "step4": 20/100, "step5": 30/100}` (Financials,
Growth Rate, Profitability, Debt) at the defaults. The blend is a plain weighted average with **no hard-fail override among the four
automated steps**.

History: the 2026-07-31 rebalance moved the weights from Financials 24%, Growth Rate 15%,
Debt 10%, Profitability ~19%, Moat 31% to Growth Rate 10%, Debt 15%,
Profitability 20% (Moat 31% unchanged, Financials 24% unchanged; those were shares of the whole, i.e. 24/10/20/15 of 69). **Motivation**: Debt's
previously-lowest weight let a genuine per-step Fail be fully absorbed by strong scores
elsewhere. Worked examples: MA (Debt a genuine Fail at 67) blended to Overall 92 "Strong Pass"
before the rebalance, 90 "Pass" after; FICO (Debt Fail at 52) went from 89 to 87, still "Pass". On 2026-10-07 the model moved again
(Moat to a multiplier, the four weights to 30/20/20/30 of 100); see docs/decisions.md.

**Known limit — re-weighting is a limited lever.** A universe-wide check at the time found the
"Overall reads Pass while a contributing step scored below 70" pattern in about 25% of tickers
(125 of 493), in two roughly equal causes: about half (62) were genuine per-step Fails diluted by
blend weighting (what the rebalance targets), and about half (63) were cases where *no* step said
"Fail" at all because the sub-70 step's own verdict gate already masked it before blending.
Re-weighting cannot fix the masked half — sensitivity testing showed even raising Debt to 25%
flipped only 4 of 111 complete-data FICO-type tickers to Fail. The masked half was later
addressed inside the steps themselves rather than by weights: Debt and Profitability now fail
any blended score below 70 (see [Debt](debt.md) and [Profitability](profitability.md), "Verdict"),
and Growth Rate floors a non-negative-growth score at 70 (and has no hard fail of its own since 2026-10-08) so a Fail-range number never sits next
to "Pass" text (see [Growth Rate](growth-rate.md)).

## What happens if Economic Moat isn't set

Economic Moat is the one manual, opt-in input. If you haven't set a Moat rating for a ticker yet, it is **scored as No moat**: the
multiplier is 0.70, exactly as if you had rated it No Moat.

- The Overall score is the Fundamentals score x 0.70, and the verdict is read from that score like any other (there is no separate verdict
  for it). In practice an unrated ticker reads Fail.
- The Analysis card and the ticker header show the note **"Moat not rated, scored as No moat"** (the header also puts it in the chip's
  tooltip; the Watchlist Analysis pill carries it as its tooltip). The note shows only on a complete assessment.
- An **incomplete** assessment (a check with missing data) stays incomplete: no score, no verdict, no note. ETFs have no Moat and no
  Overall, so they are unaffected.
- Rating the ticker (Economic Moat tab) recomputes its stored row immediately (cache only).
- This replaces the 2026-10-05 rule (an unrated ticker kept its steps-only score but could never read Pass: verdict "Moat not rated"),
  which is retired; and the old statement that leaving Moat unrated "does not penalize the number" no longer holds: unrated now costs 30%.

The rule lives in two places that must agree: `backend/scoring/overall.py::compute_overall_assessment`
and `frontend/lib/overallScore.ts::computeOverallAssessment`. Both are tested against one shared case
file, `backend/tests/fixtures/overall_verdict_cases.json`. Display: the note in the ticker header chip, the Analysis card and the Watchlist
Analysis pill. Sorts and the Financials / Growth / Profitability / Debt range filters read scores only and never see the verdict. The Screener's **Overall
filter** (2026-10-08, replacing the Overall score range) is the opposite: a multi-select over the stored `overall_verdict`, OR semantics, empty =
no filter, client-side like the other criteria. Its options are Strong pass, Pass, Pass with caution, May not pass (value `Fail`, the stored key)
and Incomplete (a row whose `overall_verdict` is null); "Pass with caution" is its own option and is not matched by "Pass", and a 91+ Overall
stored as Pass with caution is not matched by "Strong pass". The "Overall score" sort stays. The Screener card, the Watchlist pill and the Momentum stock table's Overall verdict column draw
`overall_verdict`.

## What happens if a check can't be completed

Occasionally, a required check can't be computed, and Fathom treats this two different ways
depending on why:

- If a check comes back **insufficient data** — the underlying figures genuinely weren't
  available for that company — Fathom does not guess or silently drop that check from the
  blend. Instead, the whole Overall Assessment is marked **incomplete** rather than computed,
  since a partial average built on missing data would be misleading.
- If a check comes back **not supported** — a structural exemption, such as a Bank ticker
  before its CET1 ratio has been entered, or Insurance for Debt (Debt is not applied to Insurance at all) — that one check is simply
  excluded from the Fundamentals score and the remaining checks are reweighted to add up to 100% again (Insurance: Financials, Growth Rate and
  Profitability share the whole, e.g. 42.9 / 28.6 / 28.6 at the default weights). It does **not** block the
  rest of Overall Assessment from being computed, and the Moat multiplier is applied to the reweighted Fundamentals score as usual.

See the [Glossary](glossary.md) for how both differ from a genuine Fail, and for the additional
rule that a **Pass with caution** on any one check, or a check below the pass line, carries up into Overall Assessment's own
displayed verdict even when the blended number alone would read as a plain Pass or Strong Pass.

## Valuation is separate

The **Valuation** tab answers a different question — "is this stock currently priced above or
below what the business is actually worth?" — using a completely different, price-based
methodology (DCF-style models, Price-to-Book, or Price-to-Sales-Growth depending on the
company). **Valuation is never blended into the Overall Assessment.** A company can score
strongly on Overall Assessment while its stock is expensive, or score poorly while its stock
looks cheap — these are intentionally independent reads. See [Valuation](valuation.md) for
details.

## Company type matters

Some of the checks above don't apply cleanly to every kind of company — a bank's balance sheet
doesn't work like a typical operating company's, and neither does a REIT's or an insurer's.
Fathom detects a company's type automatically (from sector/industry text, with a short list of
manually-verified ticker-level overrides for companies the text alone misclassifies) and
adjusts which checks apply accordingly, always disclosing this on the relevant tab rather than
silently changing the math. See [Company type variations](company-type-variations.md) for the
full picture.

## Screener excludes ETFs (2026-09-20)

The Screener shows stock equities only — the 5-step fundamentals framework doesn't apply to a
fund. The exclusion is unconditional, **not** a toggle, and Screener-only: the Watchlist reads
its own rows and still shows an ETF a user explicitly added.

- **How ETFs got in**: nothing ever filtered them. FMP's search returns ETFs; viewing one
  (`GET /api/tickers/{t}/score`'s fallback, or the Watchlist's `compute_ticker_score`) writes a
  `TickerScore` row, and the tracked universe then kept it in every nightly sweep
  (profile cached ⇒ "ever-viewed"; since the 2026-10-03 opt-in flip a ticker that was only opened is not in the sweeps at
  all until it is added, see [Tracked universe](tracked-universe.md)). The Screener's default universe, `all`, returns every
  `TickerScore` row in the nightly universe; an ETF is never an index constituent, so `sp500`/`dow`/`nasdaq` never held
  one. At the time of the fix the real DB had 1 ETF among 581 rows (SPY, viewed via search only).
- **Detector**: FMP `/profile`'s `isEtf`/`isFund` — the same flag
  `classify_company_type(is_fund=...)` reads (returning company type `"ETF"`; see
  [Company type variations](company-type-variations.md)). Checked against all 581 cached
  profiles at the time: SPY `isEtf=true`; the other 580 (9 ADRs included) `false/false`.
  Sector/industry text can't do this (SPY reads "Financial Services"/"Asset Management", the
  same as BLK). Already cached — no new FMP field or fetch.
- **Mechanism**: `TickerSummaryOut.is_etf` (from the profile, `data/ticker_summary.py`) →
  `TickerScore.is_etf` (nullable, `_add_missing_columns`, no backfill) → `TickerScoreOut.is_etf`.
  The Stocks Screener page (`/screener`) applies `frontend/lib/screenerFilters.ts::excludeEtfs` to the fetched rows
  once, *before* counts, Sector/Company-type options and filters derive from them, so "ETF" isn't
  even a selectable Company type. `core/main.py::screener_meta` for `universe=all` excludes them
  too, so the "X of Y" note doesn't show an ETF as a missing ticker.
- **Null handling**: `is_etf` wins when set; a row with no `is_etf` yet (every row until its next
  recompute) falls back to `company_type == "ETF"` — derived from the same profile flag — rather
  than "not an ETF", so an ETF is excluded immediately, not after the next recompute. The nightly
  3:25 `nightly_score_recompute` backfills the column (or run
  `uv run python -m pipeline.recompute_ticker_scores`, cache-only). The SQL in `screener_meta` and
  `isEtfRow` in TypeScript must stay in sync.
- **No Country filter any more**: the original write-up noted that the Screener's Country=US
  option was exchange-based and still included NYSE/NASDAQ-listed ADRs and OTC names once ETFs
  were gone. That is moot now — the Country filter (`TickerScore.country`,
  `SavedScreenerFilter.country`) was removed 2026-09-26 with non-US ticker support (see
  `docs/specs/fmp-data-and-bar-cache.md`, "US-listed tickers only"); Fathom supports US-listed
  tickers only, decided by listing venue rather than domicile, so ADRs and OTC names are
  in-universe by design. The original wording is archived in
  `docs/archive/claude-md-history-features.md`.
- **Fixed since (2026-10-02)**: `nightly_fundamentals_fetch` no longer fetches an ETF's statements: it skips known
  ETFs/funds when it builds its own universe (`load_fundamentals_fetch_universe`; see [ETF page](etf-page.md)). The
  ETFs sat in the stock-side tracked universe until the **2026-10-03 cutover**; they now have their own universe
  (`load_etf_universe`, [Tracked universe](tracked-universe.md)) refreshed by the nightly ETF job, which also writes
  their `TrendAnalysis` and `TickerLastClose` ([ETFs screener](etf-screener.md)).

## Screener excludes delisted tickers (2026-09-30)

A ticker flagged delisted (`TickerScore.delisted_at` set; see the delisted-ticker section of
[FMP data and bar cache](fmp-data-and-bar-cache.md)) appears in **no** Screener universe.
`core/main.py::screener_list` and `screener_meta` both add `delisted_at IS NULL` in every branch
(`all`, `sp500`, `dow`, `nasdaq`), so the "X of Y" count matches the rows returned. The page's
Watchlist scope is applied client-side over the `all` response and inherits the exclusion. The flag
is not exposed to the frontend and nothing here clears it. The Watchlist is unaffected: it reads its
own rows, so a delisted ticker a user explicitly watchlisted still shows there. The nightly
fundamentals fetch and score recompute still process a flagged ticker.

## P/E basis (2026-09-30)

The Screener's P/E, the ticker header's and Summary tab's **P/E Ratio**, and the Watchlist's P/E
column all read one value, `TickerScore.pe_ratio` (`TickerSummaryOut.pe_ratio`,
`data/ticker_summary.py`), and it is **trailing**:

- **Standard rule:** current price ÷ FMP TTM EPS, where EPS is `netIncomePerShareTTM` from the
  already-cached `ratios/ttm` row and the price is the nightly `TickerLastClose` close (falling
  back to the quote price when a ticker has no `TickerLastClose` row).
- **NULL** when TTM EPS is zero, negative or missing (or no price exists at all). A NULL renders as
  "—" on the Screener card and the Summary tab (a blank cell in the Watchlist table), sorts last, and
  is excluded by any active P/E range (`inRange` in `frontend/lib/screenerFilters.ts`), so loss-makers
  never pass a max-only filter.
- **ADRs** (reported currency ≠ quote currency, both known — detected from the two fields, not a
  list): use FMP's own `priceToEarningsRatioTTM` instead, because price (quote currency) over EPS
  (reporting currency) would need FX. NULL if that value is zero, negative or missing. If either
  currency is unknown the standard rule is used.
- Nothing new is fetched: the nightly cache-only recompute fills it from cached rows.

Before 2026-09-30 this was FMP's annual `priceToEarningsRatio` (fiscal-year-end price over
fiscal-year EPS), which sat next to a TTM PEG on the header — a mixed basis. The **Ratios tab is
deliberately unchanged**: it shows FMP's annual P/E history plus FMP's TTM P/E column, so its
figures can differ from the header's. No ratios spec exists yet; one is warranted.

## Beyond the Analysis and Valuation tabs

Two further, fully independent lenses exist elsewhere in the app and never feed into Overall
Assessment or Valuation in either direction:

- **Speculative Growth** — a separate classification (not a score) layered on top of the same
  fundamentals data, gated on company type, Moat, and forward growth. See
  [Speculative Growth](speculative-growth.md).
- **Technical tab** — a family of independent, price-structure-only signals (Weinstein Stage Analysis, Liquidity Zones, BB+RSI and Warren entry signals, Sector
  Heatmap, Market Breadth) computed from price bars, never from the fundamentals pipeline. See
  [Weinstein Stage](weinstein-stage.md),
  [Sector Heatmap](sector-heatmap.md), and [Market Breadth](market-breadth.md).

## The Screener lists only the opt-in universe (2026-10-02, opt-in 2026-10-03)

`universe=all` returns the `TickerScore` rows of the **tracked universe** (`data/tracked_universe.py`, see
[Tracked universe](tracked-universe.md)), not every row: a ticker is in it only through an index, a watchlist, the system set, manual
data (Moat, custom valuation, bank capital, growth-catalyst note) or because it was **added** (the Add API, or the 2026-10-03
grandfather backfill). A ticker that was only opened (browsed), or idle past 30 days (expired), is not listed, and neither is a ticker
with no view record; its row and data stay until the wipe. There is no hidden count (`ScreenerMeta.hidden_inactive` was removed with the
flip): the "X of Y" note counts the universe. The header chip recomputes a row older than 36 hours. Saved views store filters, not results,
and simply show fewer rows. The sp500/dow/nasdaq universes are unchanged. The Watchlist is unaffected (it computes its rows on demand).
