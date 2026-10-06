# Speculative Growth lens

Speculative Growth is an independent, read-only lens layered on top of the existing 5-step framework
(`scoring/speculative_growth.py`, `data/speculative_growth_data.py`). It never touches Step 1-5 or
Overall Assessment scoring.

## Gate

A ticker qualifies only when **all** of these hold:

1. `company_type == "Standard"`.
2. Economic Moat is Narrow or Wide.
3. Step 2 forward growth clears `GROWTH_GATE_MIN_PCT` (15%; imported from `scoring/step2.py` as
   `MAGNITUDE_HIGH`).
4. The company is **not durably profitable** (the profitability gate, below).

Trailing growth, gross margin, CFO sign/direction, cash runway, and PSG are informational only, never
gates. An empty or missing net-income series fails closed (it reads as durably profitable, i.e. the
ticker does not qualify), matching every other gate in the module.

The informational cash and last-two-quarters CFO direction read the cleaned statements ([Statement data
quality](statement-data-quality.md), "The shared loader"): the gated balance sheet (prior quarter when the newest is partly
filled in) and the cash-flow quarters with a placeholder newest quarter skipped. The qualification gate reads none of them.

## Profitability gate (added 2026-08-15)

`scoring/speculative_growth.py::is_not_durably_profitable` returns true when **net income is negative in
a majority (>50%) of the tracked annual + TTM periods**. It is deliberately not a flat `NI TTM <= 0`
check.

Why the gate exists: profitability was originally informational-only (to accommodate the spec's "can be
negative, acceptable" framing for NI/CFO). That had the unintended side effect that a company didn't need
to be unprofitable *at all* to qualify, so mature, thoroughly profitable Wide/Narrow-moat companies
(**MSFT, ABNB, APH, MA, TSM, AVGO, ANET**, all user-reported) qualified purely on Moat + Growth. Against
real cached data all 7 pass Moat + Growth cleanly and are durably profitable (0-1 of 10-11 tracked
annual+TTM periods negative, except ABNB at 5/10, which is still a tie, not a majority).

Why not raise the growth threshold instead: growth is roughly uniformly spread among the profitable
qualifiers (49% still clear 20%, 21% still clear 30%, ORCL/MRK/NKE-tier names still clear 40%), so a
higher threshold cannot selectively exclude mature blue-chips without also cutting legitimate high-growth
candidates.

Why majority-of-periods rather than flat TTM: a flat TTM-only check correctly excludes all 7 named false
positives but still lets through **TRMB**, which is profitable in 10 of 11 tracked periods with only the
latest TTM negative off a one-off charge, i.e. a mature company having a rough year rather than a "not
yet profitable" story (it already qualified under the old gate at moat=narrow, growth=15.6%, just above
the threshold). Majority-of-periods excludes TRMB while still including every genuine case (CRWD 10/11,
LITE 6/11, NET 11/11 negative) and leaves RKLB (8/8 negative, the original design-phase spot-check name)
unaffected.

## Validation numbers (2026-08-15)

- Sizing before the fix: **73 of 77 (94.8%)** qualifying Standard-type tickers in the tracked universe
  (S&P 500 + Dow + Watchlist) were NI-profitable; only 4 (CRWD, LITE, NET, TRMB) were genuinely
  NI-negative.
- After the fix the universe-wide qualifying count drops from 77 to **10**, and all 7 named false
  positives are excluded. The 10 qualifiers split into 3 still NI-negative (CRWD, LITE, NET) and 7 with a
  positive NI TTM but majority-negative history, i.e. recently-turned-profitable growth names (DASH, DDOG,
  DOCN, MRVL, PANW, PLTR, UBER). That is the intended "not yet *durably* profitable" reading, not new false
  positives.
- Design-phase spot-check names: RKLB, IONQ, SOUN, ACHR, JOBY. RKLB (the only one that already qualified
  on moat + growth) is unaffected by the profitability gate; IONQ, SOUN, ACHR and JOBY were already
  excluded on moat/growth grounds unrelated to profitability (no moat set, or SOUN's 4.8% growth), so the
  gate changes nothing for them.
