# moat-criteria-v5.2

The single source of criteria for every agent that runs the independent Moat check (see [Moat check](moat-check.md)). The command hands this file to each pass; it is never copied into the command. Version string: `moat-criteria-v5.2`. Same as v5.1 except the changes listed under "Version history" at the end.

You rate ONE company's Economic Moat from a qualitative reading of the business and its narrative, plus a supplied evidence block. The run date, RUN_DATE, is given in your task: use it wherever these criteria need today's date. Use WebSearch / WebFetch on company filings, earnings-call transcripts, reputable news and analysis.

## Core principle (new in v5)
The rating describes the moat AS IT IS TODAY, from OBSERVED evidence only: market share, customer retention, price increases that stuck, and the company's own margin history, over the last 3 years. Hypothetical threats can never raise or lower the rating. Only OBSERVED damage drops a tier. If the observed numbers are fine, the rating holds regardless of what rivals, technologies or regulators might do. Everything forward-looking goes in the separate "forward_threats" section, which is NOT used for the rating. Competition counts only through observed share or pricing results.

## Hard rules
- Do NOT use Morningstar in any form (no morningstar.com, no Morningstar ratings or quotes). Skip any search result from morningstar.com.
- You do not know, and must not try to find out, any rating of this company in any other system. Do not read the Fathom repo, database or any file other than: this file, your own data block, and your output path.
- No ROIC/ROE tests, no valuation arguments, no sector-peer margin comparison.
- Every web-based claim in the narrative needs an entry in "sources" with url and date (publication or filing date; write "undated" if unknown, never guess).
- Research budget: 6-7 WebSearch calls (do not exceed 8) plus WebFetch as needed: roughly 2-3 on competitors / sources of advantage, 2 on direct proof (price increases, retention, share), 2 on earnings-call transcripts (last 4-8 calls). Search budget is shared and finite: do not repeat queries.
- Cite at least TWO sources independent of the company and not Wikipedia (reputable news, trade press, analysts, third-party data vendors, competitor disclosures, regulators) for competitors and for the outcome check. The company's own filings or transcripts can be extra sources but not the only ones. If you cannot find two independent sources after an honest effort, still write the file, set "evidence_confidence":"Low" and add "evidence_note" saying what was missing.
- Keep the rating section free of hypothetical wording: in "narrative", "outcome_evidence", "source_facts" and the rating decision do not use "could", "might", "may", "would", "risk of", "threat" or similar. Write what was observed. Put what might happen only in "forward_threats", "would_lower" and "would_raise".

## A. The five sources, each with a cited fact (changed)
Rate each strong / moderate / weak / absent / unproven, with a short narrative for the strongest one or two:
- brand_monopoly: category, and do most people think of this brand first?
- switching_costs: painful or costly for customers to leave?
- barriers_to_entry: too expensive or difficult for new competitors (licences, capital, regulation, installed infrastructure)?
- network_effect: do more users make the product more valuable?
- economies_of_scale: cost advantage impossible to replicate?
EVERY one of the 5 sources must carry a cited fact in "source_facts": a number or a dated observation, with a source url and date (for example a renewal rate, a share figure, a customer count, a capacity or capex figure, a dated contract term). For a weak or absent rating, the cited fact is the observation that shows why it is weak or absent (for example "hosts routinely list on rival sites"). A source with NO cited fact is rated "unproven" and cannot carry a Wide rating: only sources rated strong WITH a cited fact count toward Wide, and only strong or moderate sources WITH a cited fact count toward Narrow. (v5.2) Wide requires at least one source rated strong WITH a cited fact.
Banks, insurers, brokers, custodians: same five sources (typically switching costs, regulatory/licensing/capital barriers and scale). No financial-ratio tests.
Competition (changed): name who could realistically take meaningful share, in "realistic_competitors". Competitors count toward the rating ONLY through observed results: share lost, retention falling, prices cut. The number or strength of competitors alone never lowers the rating, and the absence of competitors never raises it.

## B. False moats and patents (unchanged from v4)
- Technology/innovation alone is never a moat. It counts only as one layer on top of a broader source.
- Patents are never a standalone reason. A patent expiry affects the rating ONLY when one product above about 40% of revenue is the company's ONLY strong moat source (state the product share and expiry date in "single_product_flag"). For a diversified company a patent expiry goes in forward_threats only and does not change the rating.

## C. Litigation (unchanged)
Litigation, trials, disputes, fines, settlements, investigations and court rulings are EXCLUDED from the rating entirely. Do not lower or raise the rating because of any of them. They may be mentioned in forward_threats. Regulation counts for the rating only when it has already changed results (share, retention, prices) in the last 3 years; regulation that is merely pending or possible is a forward threat.

## D. Outcome check: is the moat working? (unchanged ladder, Level 3 and the stale rule changed)
Pricing power is NOT a moat source. It is the OUTCOME that shows a moat is working. Do not rate "pricing power" separately. Produce a three-state reading: "supported" | "neutral" | "contradicted", using this evidence ladder. Always judge the company against its OWN history, never against sector peers.

Level 1 - Direct proof (look first; independent sources or company disclosure):
  (a) price increases that held without visible loss of volume or customers;
  (b) customer retention / renewal / net retention staying high against the company's own history;
  (c) market share holding or growing (third-party estimate or disclosed share).
Level 2 - Only if Level 1 is unclear: use the supplied data block.
  - Own annual gross and net margin history (5-10 years): consistent or expanding = supported; stable-but-low counts as fine; never compare with peers.
  - The price-chart description is a WEAK flag only. A breakdown tells you to look harder at Level 1/3; it can never by itself make the reading "contradicted". Some tickers have only 5 years of chart.
Level 3 - Earnings-call transcripts: pricing strategy, price realization, retention/churn and share commentary. (v5.2) A statement counts as proof only when it carries a figure: a number with the period or date it describes (for example "net retention 118% in the year to June", "price realization +4% in the latest quarter"). A management claim with no figure ("we have strong pricing power") counts as no proof: it is never the outcome_supporting_item and is not entered as an outcome_evidence item. A figure reported by the company in a filing or on an earnings call counts as proof, and it is company-reported (see section F).

Contradiction (= OBSERVED damage) means: falling margins WITH a price, customer or share cause; lost customers or falling retention; share loss; or forced price cuts. A margin decline needs a stated cause on the price/customer/share side, not only a cost-side cause.
Defaults:
  - Cyclical margins (memory, storage, semiconductor equipment, commodity-linked, large capex cycles) are read as neutral unless Level 1 or 3 gives direct proof either way.
  - Company history under 5 years: margins read as neutral.
  - Financials (banks, brokers, insurers, custodians, asset managers): use NET margin only; the data block omits gross margin for them. Lean on Level 1 (retention, deposit/asset share) and Level 3.
  - Price-led businesses (COST, ROST, TJX, SCHW) and single price-setting-customer businesses (LMT, NOC, GD): "price increases held" is the wrong proof; use retention/renewal and margin stability as the evidence instead.
  - Margin steps caused by acquisition, divestiture, spin-off, accounting change, write-down or currency are not contradictions.
Record: "reading", "ladder_levels" (which of 1/2/3 supplied evidence), "outcome_evidence" (list of items: level, what it showed, URL/date or "supplied margins", and "stale": true|false), "outcome_supporting_item" (the one item relied on, or null).

Stale evidence (v5.1, date computed at run time in v5.2): evidence older than 18 months before RUN_DATE (a data period that ended before RUN_DATE minus 18 months) cannot be the outcome_supporting_item. Date an item by the period its data describes, not by the page's publication date; if the data period cannot be established, treat the item as stale. Stale items may still appear in outcome_evidence as context and must be marked "stale": true.

Observed damage list (v5.1): every record carries "observed_damage", a list with one entry for EVERY observed decline in market share, customer retention, price (price cuts, falling price realization) or own-history margin in the last 3 years, whether or not it changes the rating. Each entry: {"metric": "...", "change": "from X to Y", "period": "...", "counted": "yes|no", "reason": "one line"}. "counted: yes" means the decline is treated as a contradiction under the rules above (and the reading is then "contradicted"); "counted: no" means it is not (for example a cost-side margin cause, a cyclical default, an acquisition or currency step, a one-quarter blip against a strong multi-year record, or a decline from a record peak that stays within the company's own normal range), with the reason. Use an empty list only if you searched for declines and found none. Do not hide a decline because it is small; list it and say why it does or does not count.

## E. Rating (changed)
- Wide = at least one source rated strong WITH a cited fact AND reading "supported" (at least one supporting item) AND no observed damage (no contradiction). (v5.2) A Wide rating may rest entirely on company-reported evidence (company filings, earnings releases, transcripts with a figure, investor decks). Who reported the proof never changes the rating, only evidence_confidence (section F).
- Stale supporting item (v5.1): if the supporting item is stale (older than 18 months before RUN_DATE), it cannot be the outcome_supporting_item; use a fresher item or the reading falls back to "neutral" (and the rating to Narrow if the source is strong). When this rule changed the reading, say so in "evidence_note".
- Narrow = a real source that is moderate (with a cited fact), OR a strong source with a "neutral" reading.
- Observed damage (a "contradicted" reading) moves the rating down one tier, (v5.2) counted from the tier the sources justify: a strong source with a cited fact justifies Wide, so a contradicted reading gives Narrow; a moderate source (and no strong one) justifies Narrow, so a contradicted reading gives No Moat.
- A "neutral" reading never lifts and never lowers a rating.
- No Moat = no source rated moderate or better with a cited fact, or only a false moat.
- There is NO threat test and NO time-window test. A named, credible, even likely future threat does not change the rating. There is no "several significant competitors" cap. Do not use any rule of the form "no named threat within N years".
- "durability_years_estimate" is how long the advantage has already been OBSERVED to persist ("20+", "10-20" or "<10"), informational only; it never changes the rating.

## F. Evidence confidence (replaces v4 "confidence"; changed in v5.2)
"evidence_confidence" = High / Medium / Low, set ONLY by (1) source quality, (2) how many independent sources back the sources-of-advantage and outcome facts, (3) whether the proof that the moat is working is company-reported only, and (4) at reconciliation, whether the two passes agree. Threats, and how scary the outlook is, never affect it.
Independent means: not the company and not Wikipedia. Third-party data vendors (Euromonitor, Circana and similar), regulators, competitors' disclosures, analysts and independent press reporting its own measurement are independent. The company's filings, earnings releases, transcripts, investor decks, and press articles that merely relay company-reported figures are company-reported. The supplied margins in the data block are the company's own reported figures and are company-reported.
Proof that the moat is working (v5.2) = the outcome_supporting_item plus the other outcome_evidence items that support the reading. The facts behind the five source ratings are not part of it.
Guide for each pass: High = 3+ independent sources including direct (Level 1) proof from independent data; Medium = 2 independent sources, or direct proof only from a vendor; Low = fewer than 2 independent sources, or stale/undated evidence, or (v5.2) proof of the working moat that comes from the company alone. Short financial history is irrelevant. (At reconciliation: the lower of the two passes; if the two ratings differ the result is "inconclusive" and confidence is Low. Reconciliation is done by the code, not by you.)
"proof_basis" (v5.2): "company_reported_only" when the outcome_supporting_item and every other supporting outcome_evidence item are company-reported; then evidence_confidence is Low and "evidence_note" says what independent proof was not found. Otherwise "independent" (at least one supporting item is independent). The card shows "unverified by independent source" for "company_reported_only". proof_basis never changes the rating.

## G. Forward threats (changed in v5.1; still NOT used for the rating)
"forward_threats": {"threat_level": "Low|Moderate|High", "threats": [...]}.
Each tripwire must be a NUMBER metric with a numeric review level, so the tests below can be run. Give 1-4 threats (an empty list is allowed only for overall Low).
Each threat has exactly: "name" (plain English), "level" (Low|Moderate|High), "level_test" (which test put it at that level, see below), "what_could_happen" (ONE sentence), "observed_so_far" (what is actually seen today, with a number or date), "tripwire": {"metric": "...", "value_now": "...", "review_level": "..."}.
Threat level definitions (v5.1):
- Low = no credible path to hurt the moat is visible.
- Moderate = a credible path exists AND no tripwire metric is within 10% of its review level.
- High = a tripwire metric is within 10% of its review level (relative gap |value_now - review_level| / |review_level| <= 10%, or the level is already breached), OR the metric has already moved against the company in each of the last two reported quarters or periods.
"level_test" must name the test in words and show the numbers, for example "Moderate: gap to review level is 38% (value 72.5 vs level 65); metric rose in the last two quarters" or "High: moved against the company in the last two reported quarters (62% to 60% to 58%)". "threat_level" overall = the highest level among the threats (Low if none).
Review levels must be DERIVED, not invented (v5.1): base each on the company's own history (for example its worst level in the last 5 years) or a stated fraction of its recent level, and say which inside the "review_level" text, for example "below 61% (its worst annual level in the last 5 years, 2022)" or "below 85% of the latest four-quarter average (14.2)". A round number with no stated basis is not allowed.
threat_level is a separate reading and never changes the rating or evidence_confidence. Include patent expiries, pending regulation and litigation here when relevant.

## H. Plain-English lines (replace erosion_watch)
"would_lower": what, if it showed up in the numbers, would lower the rating. "would_raise": what would raise it. Plain English, no jargon, short sentences (two at most each). Both must name something that can be measured.

## Output
Write ONE JSON file (path given in your task) with exactly these keys:
{"ticker":..., "criteria_version":"moat-criteria-v5.2", "checked_date":"<RUN_DATE, YYYY-MM-DD>",
 "suggested_rating":"wide_moat|narrow_moat|no_moat",
 "sources_rating":{"brand_monopoly":"strong|moderate|weak|absent|unproven","switching_costs":...,"barriers_to_entry":...,"network_effect":...,"economies_of_scale":...},
 "source_facts":{"brand_monopoly":{"fact":"...","source":"url","date":"..."}|null,"switching_costs":...,"barriers_to_entry":...,"network_effect":...,"economies_of_scale":...},
 "moat_types":["..."], "realistic_competitors":["..."],
 "reading":"supported|neutral|contradicted", "ladder_levels":[1,2,3], "outcome_evidence":[{"level":1,"item":"...","source":"url or supplied margins","date":"...","stale":true|false}],
 "outcome_supporting_item":"..."|null, "margins_note":"one sentence on what the supplied margins did or did not show",
 "proof_basis":"independent|company_reported_only",
 "observed_damage":[{"metric":"...","change":"from X to Y","period":"...","counted":"yes|no","reason":"one line"}],
 "single_product_flag":null|"...",
 "durability_years_estimate":"20+|10-20|<10",
 "narrative":"3-5 sentences, observed facts only",
 "evidence_confidence":"High|Medium|Low", "evidence_note":null|"...",
 "forward_threats":{"threat_level":"Low|Moderate|High","threats":[{"name":"...","level":"Low|Moderate|High","level_test":"...","what_could_happen":"...","observed_so_far":"...","tripwire":{"metric":"...","value_now":"...","review_level":"... (with its derivation)"}}]},
 "would_lower":"...", "would_raise":"...",
 "sources":[{"url":"...","date":"...","claim":"..."}]}
A source rated "unproven" has "source_facts" value null. Then reply with one line: the ticker and suggested_rating.

## Version history
- **v5**: observed-evidence-only principle, cited fact per source, forward_threats kept out of the rating.
- **v5.1**: 18-month stale rule, observed_damage list, derived tripwire review levels, defined threat-level tests, `would_lower` / `would_raise`, and an independent-support rule (a Wide rating needed at least one independent supporting item, otherwise capped at Narrow).
- **v5.2** (2026-10-12): the independent-support rule is removed from the rating (Wide on company-reported evidence stays Wide; company-only proof now sets `evidence_confidence` Low and `proof_basis` `company_reported_only`, with a card label); vendors count as independent; a contradicted reading counts down from the tier the sources justify; "clear" removed from the Wide requirement; Level 3 needs a figure; no hard-coded dates (RUN_DATE, the 18-month cutoff and `checked_date` are set at run time); "last 3 years" throughout; the `independent_support` and `rule_effects` output keys removed (`rule_effects` had only the 18-month rule left, whose effect is noted in `evidence_note` and visible in the `stale` flags); no `tag` field.
