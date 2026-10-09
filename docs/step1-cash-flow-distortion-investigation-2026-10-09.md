# Step 1 and structurally distorted cash flow (IBKR, GM): investigation, 2026-10-09

Report only. No code, spec or database change. Cache only, no FMP call; a read-only (`mode=ro`) engine was patched onto every module's `engine`, the
scratch scripts are deleted. The harness reproduces the stored `TickerScore` Overall for all 471 non-exempt tickers it scored (0 mismatches), so the
counterfactuals below start from the real numbers. Follow-up to the open item in `docs/specs/stuck-check.md` ("IBKR and GM in Step 1").

Weights in force (the saved set, `weights_version` 8, not the code defaults): Step 1 Revenue 30 / Net Income 20 / CFO 25 / Margins 10 / FCF 15;
Overall Financials 35 / Growth 20 / Profitability 20 / Debt 25. `SCORE_FORMULA_VERSION` 6.

## 1. Current behaviour

Both are `Standard` and neither is Step 1-exempt (`_detect_exemption` returns `None`). IBKR: sector Financial Services, industry "Investment -
Banking & Investment Services" would match Bank on "banking", but IBKR is in `NON_LENDER_TICKER_OVERRIDES` (2026-09-05: no deposit-liability tag),
so Standard. GM: Consumer Cyclical / Auto - Manufacturers, Standard by default.

| Metric (weight) | IBKR score / pattern | points | GM score / pattern | points |
|---|---|---|---|---|
| Revenue (30) | 100 uptrend_dips | 30.0 | 79 uptrend_dips | 23.7 |
| Net Income (20), no Operating Income backup | 99 uptrend_dips | 19.8 | 0 decline_dips | 0.0 |
| CFO (25) | 88 uptrend_dips | 22.0 | 77 uptrend_dips | 19.2 |
| Margins (10) | 95 (O 95, G 99, N 92; O binds) | 9.5 | 46 flat_dips (G 46, O 58, N 66; G binds) | 4.6 |
| FCF (15) | 88 uptrend_dips | 13.2 | 86 uptrend_dips | 12.9 |
| **Step 1** | **94 Strong Pass** | | **60 Fail ("May not pass")** | |

Stored rows (computed 2026-10-09): IBKR Step 2 90, Step 4 74, Step 5 61 (Fail), Wide moat x1.0, steps score 80.95, **Overall 81 "Pass with
caution"** (the caution is the Debt step below 70, not Financials). GM Step 2 70, Step 4 45, Step 5 48, No moat x0.70, steps score 56.0,
**Overall 39 Fail**.

## 2. What is distorted (cleaned annual statements, $M)

### IBKR

| FY | Revenue | NI (income stmt) | NI (cash-flow stmt) | CFO | Capex | FCF | FCF / IS NI | change in WC | payables | receivables | other WC |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016 | 1,381 | 84 | 699 | 635 | -27 | 608 | 7.2 | -174 | 4,647 | -2,328 | -2,493 |
| 2017 | 1,595 | 76 | 793 | 1,065 | -28 | 1,037 | 13.6 | 121 | 5,817 | -11,508 | 5,812 |
| 2018 | 2,317 | 169 | 1,125 | 2,356 | -36 | 2,320 | 13.7 | 1,122 | 445 | 3,311 | -2,634 |
| 2019 | 2,573 | 161 | 1,089 | 2,666 | -74 | 2,592 | 16.1 | 1,404 | 8,255 | -6,782 | -69 |
| 2020 | 2,420 | 195 | 1,179 | 8,068 | -50 | 8,018 | 41.1 | 6,773 | 19,634 | -7,277 | -5,584 |
| 2021 | 2,940 | 308 | 1,636 | 5,896 | -77 | 5,819 | 18.9 | 4,063 | 9,754 | -20,689 | 14,998 |
| 2022 | 4,192 | 380 | 1,842 | 3,968 | -69 | 3,899 | 10.3 | 1,915 | 7,561 | 13,774 | -19,420 |
| 2023 | 7,787 | 600 | 2,812 | 4,544 | -49 | 4,495 | 7.5 | 1,510 | 7,817 | -4,488 | -1,819 |
| 2024 | 9,316 | 755 | 3,407 | 8,724 | -49 | 8,675 | 11.5 | 5,075 | 14,331 | -21,204 | 11,948 |
| 2025 | 10,232 | 984 | 4,357 | 15,811 | -67 | 15,744 | 16.0 | 11,237 | 38,993 | -35,856 | 8,100 |

What the data supports:

- **Capex is about zero** (27-105 per year, under 1% of CFO), so FCF is CFO. There is no capex story; Step 1's FCF series is a second copy of CFO.
- **CFO is driven by working-capital lines, not earnings.** Change in WC is 58-84% of CFO in 2020, 2021, 2024 and 2025 (e.g. 2025: 11,237 of 15,811). The
  payables (customer credit balances) and receivables (customer margin loans) lines swing by up to 39 billion a year, with opposite signs and no relation
  to earnings. FY2025 as-reported (the only year cached): increase in payables to customers +38,993, increase in receivables from customers -26,045,
  securities borrowed +6,220, securities loaned +8,503.
- **The income-statement Net Income is the share attributable to IBKR Inc.** (Up-C structure): 10-23% of the cash-flow statement's consolidated Net
  Income (84 vs 699 in 2016, 984 vs 4,357 in 2025). FCF / income-statement NI of 7-41 is therefore partly an NI-definition effect; against consolidated
  NI the ratio is 0.9 (2016) to 3.6 (2025), 6.8 in 2020. This does not hurt Step 1's Net Income score (shape only, 99), but it means any "cash
  conversion" read of IBKR is wrong by a factor of 4-10 on definition alone.

Not shown by the cache: the split of each year's WC lines into customer flow and own operations before FY2025 (as-reported holds one year), and whether
segregated-cash movements sit inside CFO. IBKR has no `sec_company_facts` row. **Filing check:** the 10-K cash-flow statements, especially the
"cash, cash equivalents, restricted cash and segregated cash" reconciliation.

### GM

| FY | Revenue | NI | CFO | FMP capex | FCF | FCF / NI | D&A | SEC PP&E | SEC leased-vehicle purchases | SEC lease proceeds |
|---|---|---|---|---|---|---|---|---|---|---|
| 2016 | 149,184 | 9,427 | 16,607 | -27,879 | -11,272 | -1.2 | 9,819 | 8,384 | 19,495 | 2,554 |
| 2017 | 145,588 | 36 | 17,328 | -27,633 | -10,305 | n/m | 12,261 | 8,453 | 19,180 | 6,667 |
| 2018 | 147,049 | 8,084 | 15,256 | -25,497 | -10,241 | -1.3 | 13,669 | 8,761 | 16,736 | 10,864 |
| 2019 | 137,237 | 6,732 | 15,021 | -23,996 | -8,975 | -1.3 | 14,118 | 7,592 | 16,404 | 13,302 |
| 2020 | 122,485 | 6,427 | 16,670 | -20,533 | -3,863 | -0.6 | 12,815 | 5,300 | 15,233 | 13,399 |
| 2021 | 127,004 | 10,019 | 15,188 | -22,111 | -6,923 | -0.7 | 12,051 | 7,509 | 14,602 | 14,393 |
| 2022 | 156,735 | 9,934 | 16,043 | -21,187 | -5,144 | -0.5 | 11,290 | 9,238 | 11,949 | 14,234 |
| 2023 | 171,842 | 10,127 | 20,930 | -24,610 | -3,680 | -0.4 | 11,888 | 10,970 | 13,640 | 13,033 |
| 2024 | 187,442 | 6,008 | 20,129 | -26,109 | -5,980 | -1.0 | 12,389 | 10,830 | 15,279 | 10,892 |
| 2025 | 185,019 | 2,697 | 26,867 | **-15,793** | **11,074** | 4.1 | 14,588 | 9,303 | 15,793 | 10,095 |

(SEC columns come from the cached `sec_company_facts` row, 10-K fiscal-year values.)

What the data supports:

- **FMP's `capitalExpenditure` for GM is PP&E plus purchases of leased vehicles, to the dollar, FY2016-FY2024** (2024: 10,830 + 15,279 = 26,109;
  2020: 5,300 + 15,233 = 20,533). Leased-vehicle purchases are 55-74% of "capex". The matching proceeds from leased-vehicle liquidations (10-14 billion a
  year) are not in FMP's capex, so purchases are deducted without the sale proceeds being credited: FCF is -3.7 to -11.3 billion in every year 2016-2024
  on 6-10 billion of net income. CFO also carries the add-back of the leased vehicles' depreciation (D&A 10-15 billion).
- **FY2025 is a different definition, not an improvement.** FMP capex 15,793 equals the leased-vehicle line alone; the 9,303 PP&E is missing. On
  the old definition FY2025 capex is 25,096 and FCF 1,771, not 11,074. The same signature appears for **CAT** (FY2025 FMP capex 1,465 = the
  equipment-on-lease line; PP&E 2,821 missing; FY2016-2024 match PP&E + lease). Of 144 tickers with cached SEC facts and a PP&E tag, 8 differ from the PP&E
  tag by more than 25% in the latest FY (CAT, GM, CSGP, DOCN, INTU, SEZL, SOUN, STX); only CAT and GM were examined. GM's FCF score is 86 either way
  (still "uptrend" from -6.0 billion to +1.8 billion), so this defect does not move GM's Step 1.
- FMP CFO equals SEC `NetCashProvidedByUsedInOperatingActivities` for every GM year. FMP net income differs from SEC `NetIncomeLoss` (FY2017: FMP 36,
  continuing operations 330, SEC -3,864; later years 0-230 higher): a field-definition difference for a filing check, not a Step 1 issue (the
  engine reads shape, and 2017 is one dip of a recovered series).
- **Conflict with `stuck-check.md`:** the spec text says GM's "financing receivables run through operating cash flow". The cache says otherwise:
  `PaymentsToAcquireFinanceReceivables` (36.7 billion in 2025) and collections (35.1 billion) are investing-type tags, GM's net investing cash is -16.1
  billion, and neither amount is in FMP's CFO or capex. The distortion the data shows is **leased-vehicle purchases inside capex plus the depreciation
  add-back inside CFO**. **Filing check:** the GM 10-K cash-flow statement (confirms which section holds the receivable flows).

## 3. Counterfactuals

"a1" is the existing exempt wrapper as it stands: CFO, FCF **and Margins** skipped, Revenue 56.52 / Net Income 43.48 (the saved-weight "Bank" table).
"a2" skips CFO and FCF only and keeps Margins (proportional renormalisation over Revenue / NI / Margins, 50 / 33.3 / 16.7; the code's equal-thirds middle
table gives 99 / 45, the same verdicts). "b" skips FCF only (proportional over the other four). Overall uses the stored Step 2/4/5, Moat and the saved
Overall weights, rounded once.

| | Step 1 | Overall | steps score |
|---|---|---|---|
| **IBKR** baseline (c) | 94 Strong Pass | 81 Pass with caution | 80.95 |
| a1 | 100 Strong Pass | 83 Pass with caution | 83.05 |
| a2 | 99 Strong Pass | 83 Pass with caution | 82.70 |
| b | 96 Strong Pass | 82 Pass with caution | 81.65 |
| **GM** baseline (c) | 60 Fail | 39 Fail | 56.00 |
| a1 | 45 Fail | 36 Fail | 50.75 |
| a2 | 47 Fail | 36 Fail | 51.45 |
| b | 56 Fail | 38 Fail | 54.60 |

**No verdict changes under any option for either ticker.** IBKR is Strong Pass on Revenue 100, Net Income 99 and Margins 95 alone; its CFO and FCF (88)
pull it down slightly, so exempting them raises it by 6 points. GM's cash-flow metrics **flatter** it (CFO 77, FCF 86 against Net Income 0 and
Margins 46): exempting them lowers GM by 13-15 Step 1 points.

**GM attribution** (points lost against 100 per metric, at the saved weights): Net Income 20.0, Revenue 6.3, CFO 5.8, Margins 5.4, FCF 2.1; total
39.6, which is why Step 1 is 60.4. Net Income alone is half of what GM loses (score 0: 10.1 billion in 2023 to 6.0 to 2.7 billion, the last year
down 55%, which triggers the last-year cut); cash-flow metrics supply 32 of the 60 points. A Net Income score of 50 alone would put GM at 70. GM's
Overall Fail does not depend on Step 1 at all: with No moat the multiplier is 0.70 and the other steps are Growth 70, Profitability 45, Debt 48, so
Overall is 39 at Step 1 = 60, 42 at 70 and **49 at 100**.

## 4. Universe scan

582 tracked stocks, 109 already Step 1-exempt (Bank, Insurance, REIT, Commodity), 473 scored on all five, 471 with a Step 1 score. Signals on the last
three completed fiscal years of the cleaned statements: FCF / NI above 5 or FCF negative with NI positive, CFO / NI above 5 or CFO negative with NI
positive, capex above CFO, CFO sign flips, cash-flow-statement NI above 2x income-statement NI. 70 tickers are flagged, 27 of them Utilities; 43 are not.
A separate "CFO and NI disagree in sign in 2 of the last 6 years" rule hits 68 tickers, mostly software companies whose Net Income is negative on
stock compensation while CFO is positive. **No data rule separates a structural distortion from a weak or lumpy company without reading line items.**
SEC facts exist for 214 tickers only (not F, DE, PCAR, TSLA, URI, HOOD, ARES or IBKR); as-reported holds one fiscal year for 37.

Before / after, "a1" in the format Step 1 (Overall): baseline -> a1 -> a2.

### Distorted for a structural reason the data shows, or partly shows

| Ticker | Industry | Evidence | Step 1 -> a1 / a2 | Overall -> a1 / a2 |
|---|---|---|---|---|
| IBKR | Inv. banking & brokerage | customer payables / receivables in CFO, capex 0 (section 2) | 94 SP -> 100 / 99 | 81 PwC -> 83 / 83 |
| GM | Auto manufacturers | leased vehicles in FMP capex, SEC-confirmed (section 2) | 60 Fail -> 45 / 47 | 39 Fail -> 36 / 36 |
| HOOD | Capital markets | CFO vs NI sign disagree in 2023 and 2024 (CFO +1,181 / -157, NI -541 / +1,411); FY2025 as-reported: payables to customers +3.4B, securities loaned +4.2B, receivables +9.1B. One year of tags only | 67 Fail -> **94 SP** / 90 Pass | 43 Fail -> 51 / 50 Fail |
| KKR | Asset mgmt | CFO -6.0 / -7.2 / -5.3 / -1.5B (FY20-23) against NI +2.0 / +4.7 / -0.5 / +3.7B, then +6.7B; cash-flow-statement NI 1.4x income-statement NI. Mechanism (consolidated investment vehicles) not visible in the tags | 70 Pass -> **64 Fail** / 54 Fail | 45 Fail -> 44 / 41 Fail |
| APO | Asset mgmt | CFO -1.6B (FY20) then +1.1 to +7.5B; sign flips vs NI | 75 Pass -> 82 / 70 Pass | 53 Fail -> 55 / 52 Fail |
| ARES | Asset mgmt | CFO -426 / -2,596 / -734 / -233 then +2.8B / +3.3B on NI 152-527; cash-flow NI 2.3x income-statement NI | 79 Pass -> 89 / 80 Pass | 51 Fail -> 53 / 51 Fail |
| BX | Asset mgmt | cash-flow NI 1.5x income-statement NI; **FMP FY2025 CFO 1,861 vs 10-K facts 4,663**; Overall incomplete (not scored) | 52 Fail -> **83 Pass** / 73 Pass | none |

(KKR FY2025: FMP CFO 9,684 against 478 in the 10-K facts. A data question for a filing check in its own right.)

**Utilities (31 of Utility type in the scored set).** FCF is negative against positive NI by regulated-capex design (capex / CFO 1.0-2.1, FCF / NI
-0.0 to -3.8). This is structural and the stuck-check card already marks it Not applicable, but Step 1 deliberately scores Utility on all five
(`financials.md`). Applying a1 would move Step 1 Fail to Pass for 13 of 31 (AEE, CEG, CMS, CNP, ED, ES, ETR, LNT, NRG, PCG, PEG, SO, SRE) and no Overall
verdict. Outside the brief; listed as a decision.

### Data-definition defects, not business structure

CAT (FY2025 capex = lease line only; FCF shown 10.3 billion, 7.5 billion on the FY2016-2024 definition; Step 1 90 Pass either way), GM FY2025 (above),
KKR / BX FY2025 CFO against the 10-K facts.

### Checked and not distorted, or just a weak or lumpy cash-flow company (Step 1 should keep scoring)

- **Payment and exchange companies holding customer funds**: V, MA, PYPL, GPN, CPAY, FISV, CME, CBOE, NDAQ: FCF / NI 0.9-1.6 for the last three years,
  no sign flips. Not distorted. COIN's CFO tracks its NI in sign (2023-25).
- **Asset managers without consolidation effects**: BLK, TROW, SEIC, BEN: FCF / NI 0.6-1.4.
- **Captive-finance industrials**: CAT (FCF / NI 1.0, lease purchases 1.2-1.5 billion are 12% of CFO; the 15 billion of finance-receivable
  originations are investing-type), DE (0.5), PCAR (0.8), F (see below), TSLA (0.5), URI (0.2: rental fleet purchases are the business). DE, PCAR, F, TSLA,
  URI have no SEC facts cached: the data shows no distortion signal, a filing check is the only way to be sure.
- **CFO far above NI because NI is depressed by non-cash or one-off charges** (not a distortion, CFO is the better number): DD, TKO, DASH, F (NI -8.2B in
  2025 on impairments, CFO 21.3B), IVZ, BMY, MMM, SWK, DDOG, P, TSN, MRVL, CRL, MELI.
- **Capex above CFO from growth capex**: NBIS, CRWV, IREN, INTC, ORCL, LITE, COHR, ALB, APD, AAP, ECHO, NCLH, LUV, AES, KTOS, SPCX.
- **CFO sign flips from working-capital cycles**: MGM, EXPE, ADM, BG, DAL, J, CIEN, ZBRA, FLEX, GEN, SMCI (8 flips), HUT.

Applying a1 to **all** 471 non-exempt tickers would flip 65 Step 1 verdicts and 30 Overall verdicts across the Pass family and Fail; this is the
reason the choice of set matters (section 5).

## 5. Mechanism options

| | (i) hand-maintained list | (ii) new exemption type through `_detect_exemption` | (iii) industry rule | (iv) reuse the stuck-check Settings list |
|---|---|---|---|---|
| Blast radius | exactly the listed tickers | same as the set that feeds it | whole industries: Inv. banking + Capital Markets = IBKR, HOOD, CRCL, HUT (CRCL Pass -> Fail, HOOD Fail -> Strong Pass); Auto - Manufacturers = GM, F, TSLA, RIVN (TSLA Pass -> Fail); Asset Management = 10 (KKR Pass -> Fail, BX Fail -> Pass, BLK / TROW / SEIC / BEN no distortion) | the Settings list (2 today) |
| Maintenance | a new ticker needs a manual check, as for `NON_LENDER_TICKER_OVERRIDES` (19) and `COMMODITY_EXEMPTION_TICKER_OVERRIDES` (2) | none beyond its feed | none, but wrong in both directions | an edit in the UI changes scores |
| False positives | none by construction | per feed | high: V, MA, PYPL, BLK, TROW, TSLA sit in the same industries as the distorted names | none by construction |
| False negatives | any unlisted ticker (HOOD, KKR, APO, ARES today) | per feed | CAT, DE, PCAR are in "Agricultural / Industrial - Machinery"; GM-type captive finance is not an industry | same as (i) |
| `SCORE_FORMULA_VERSION` | bump or recompute (a step's scoring changes) | same | same | a Settings edit would need a recompute path; `stuck-check.md` says edits "take effect on next page load, no recompute" |
| Screener / Watchlist / Momentum | Screener, Watchlist and the Momentum Overall pill read the stored `TickerScore`, so they change on the recompute; nothing else | the same, plus Step 1 card text and Speculative Growth (below) | same | same |

Points specific to (ii): `_detect_exemption`'s return value is `Step1Out.cfo_exempt_reason`, which the Step 1 card, the Historical Trends grid and
**Speculative Growth** read; `speculative_growth_data.py:100` treats any non-None value as "not applicable" and shows it as the company type. A new
exemption string would therefore also switch Speculative Growth off for these tickers, and would need its own card text. A string outside
`MARGINS_EXEMPT_TYPES` keeps Margins and revives the middle weight table, which `financials.md` calls unreachable today. A string inside it drops Margins
(a1), which for GM removes a real weak signal (gross margin 46).

Points specific to (iv): the list is a database row edited in the UI, the stuck-check spec's hard rule is that the card "feeds nothing", and the list's
per-ticker row selection (rows 1, 2's FCF part, 3, 5, 6) has no meaning for Step 1 (IBKR's entry exempts the share-count row, which Step 1 never
reads).

**Recommendation.** (ii) fed by (i): one new exemption value for the Step 1 wrapper, membership a small code-resident, hand-verified ticker set in the
style of `NON_LENDER_TICKER_OVERRIDES` with a per-ticker reason in `company-type-variations.md`, kept separate from the stuck-check list. No industry
rule: the scan found no signal that separates structural from lumpy without reading line items. Membership limited to tickers whose distortion the
cache or a filing check confirms.

## 6. Risks and open decisions

**Verdicts that flip under the recommended option.**

- Set {IBKR, GM}: **none**, at Step 1 or Overall, under a1, a2 and b. Scores move: IBKR Step 1 94 -> 100 (a1) / 99 (a2), Overall 81 -> 83; GM Step 1
  60 -> 45 / 47, Overall 39 -> 36.
- Adding the other names with data evidence: HOOD Step 1 Fail -> Pass (a2) / Strong Pass (a1), KKR Step 1 Pass -> Fail, BX Step 1 Fail -> Pass (Overall
  incomplete). **No Overall verdict flips in the structural set** (HOOD, KKR, APO, ARES, IBKR, GM stay in their Overall family).
- Pass-family to May-not-pass at Step 1: KKR (set above). May-not-pass to Pass: HOOD, BX.

**Inconsistencies with existing specs.**

1. `NON_LENDER_TICKER_OVERRIDES` (2026-07-28 / 2026-09-05) moved IBKR, HOOD, KKR, APO, ARES, BX and others **out of Bank on purpose** so that they get
   Standard Step 1 scoring, because Bank treatment (including the CFO / FCF exemption) was wrong for non-lenders. A CFO exemption for IBKR partly reverses
   that, on a different ground (cash-flow shape, not lending). The docs should say so.
2. `stuck-check.md` describes GM's distortion as financing receivables inside operating cash flow; the cache says leased-vehicle purchases inside capex
   (section 2). Needs a spec correction either way.
3. Exemption philosophy ("judge consistency by trend shape, avoid cliffs"): a ticker list is a cliff by construction, but so is every company-type
   exemption. The cleaner fit is to leave the engine alone and only choose the weight table.
4. `financials.md` "the middle table is no longer reached by any company type" stops being true under a2.
5. GM's score gets **worse** under any exemption (the distortion flatters it). If the aim is "remove the distortion", the honest result is that
   GM's Step 1 drops 13-15 points and IBKR's rises 5-6.

**Decisions for you.**

1. Whether to change Step 1 at all: no Overall or Step 1 verdict changes for IBKR or GM, so the case is score honesty, not verdicts.
2. a1 (Revenue + Net Income only, Margins also skipped) or a2 (Margins kept)?
3. Membership: only IBKR and GM, or also HOOD, KKR, APO, ARES, BX (evidence is weaker: one year of tags for HOOD, sign pattern only for the asset managers)?
   Verdict-moving tickers are HOOD, KKR, BX.
4. GM specifically: exempt CFO / FCF at all, given that they help it? Or correct the FMP definition issue instead (FY2025 capex)?
5. What the new value is called and what the Step 1 card and Speculative Growth should show for it.
6. Bump `SCORE_FORMULA_VERSION` to 7, or recompute without a bump as on 2026-10-08.
7. Utilities (13 of 31 flip Fail to Pass at Step 1 if exempt): leave as is, as the specs choose today?
8. Filing checks worth doing before any list is final: IBKR 10-K cash-flow statement; GM 10-K (which section holds the receivable flows); KKR / BX FY2025
   CFO against FMP; HOOD, KKR, APO, ARES operating-section content.
9. Separate small follow-up: FMP latest-FY `capitalExpenditure` for GM and CAT drops PP&E (FCF overstated 9.3 and 2.8 billion), and KKR / BX FY2025 CFO
   disagrees with the 10-K facts. A cached-vs-SEC check could be a standing health check.
