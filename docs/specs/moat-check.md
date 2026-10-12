# Independent Moat check

**Status: built except the `/moat-check` command (code phases 1 to 4, 2026-10-12).** The table, read API, block and save scripts and the card exist; until the command exists (phase 5) a check can be saved only by running the block and save scripts by hand. The criteria themselves are final and live in [Moat criteria](moat-criteria.md) (`moat-criteria-v5.2`).

The independent Moat check is a second opinion on a ticker's Economic Moat, run on demand from Claude Code with `/moat-check <ticker>` and shown as a card on the Economic Moat tab. It rates the moat from a written rubric and web research, **without ever seeing the rating you set**, and the card then says whether it **agrees** or **differs** from your rating. It is advisory: it never changes your rating, the Moat multiplier, the Overall score or any stored score (see [Economic Moat](economic-moat.md) for the rating that scores).

## What you see

On the Economic Moat tab, below the rating selector, an **Independent check** card. It has these states:

| State | What the card shows |
|---|---|
| **Not checked yet** | "Not checked yet. Run /moat-check <ticker> in Claude Code." (with the ticker filled in). Every ticker starts here; there is no bulk import. |
| **Checked, passes agree** (status `stable`) | The check rating (Wide / Narrow / No moat, drawn with the same tier labels as the selector), the verdict against your rating (**agrees** or **differs**, see below), evidence confidence, the checked date and criteria version, then **pass 1's detail**: the five sources with their cited facts, the outcome reading and its evidence, the observed-damage list, the forward threats with their tripwires, the "would lower" / "would raise" lines and the evidence note. |
| **Checked, passes split** (status `inconclusive`) | "Inconclusive: the two passes disagree" with **both passes** side by side (rating, reading, confidence, strongest source and facts). **No suggested rating, no agrees/differs.** Confidence is Low. |
| **Loading / error** | The tab's usual loading line; on error "Couldn't load Independent check — <message>". A stored row the card cannot read shows "This check can't be displayed."; an error boundary around only this card keeps a bad row from taking down the Moat tab. |

- **Agrees / differs.** The card compares the check rating with your set rating and shows one word. Nothing in the check stores or assigns a reason for a difference. If you have not set a rating, the card shows "No set rating" and no agrees/differs (the ticker is still scored as No moat, as always).
- **Unverified label.** When `proof_basis` is `company_reported_only`, the card shows an **"Unverified by independent source"** pill (warn tone) and a warn-toned Low confidence. The rating itself is not changed by it.
- **Older criteria.** If the stored row's criteria version is not the current one, the card says "Checked under criteria v5.x" so an old row is not read as current (`criteria_is_current` from the API).
- **Words.** The card uses the Moat tier labels only. It never draws a verdict word ("Fail" is retired as a display word, see [Overview](overview.md)), and it has **no Apply button**: v1 is read-only, and the only way to change your rating stays the selector and its confirm step.
- **Rendering.** Everything the check wrote (facts, narrative, names, tripwires) is rendered as **plain text**: no HTML, no Markdown. A source URL becomes a link only if it parses as `http:` or `https:` (opened in a new tab with `rel="noopener noreferrer"`); any other scheme is shown as text. Model output built from web research is untrusted.
- **Layout (card below the rating panel, same surface and border).** Header: "Independent check", the criteria version and checked date on the right, and "passes disagree" when inconclusive. Always visible, in this order: three metric tiles (**Rating today**, captioned "observed evidence only"; **Evidence confidence**, warn-toned when Low; **Forward threat level**, captioned "not scored"); one pill row (**Agrees with your rating** / **Differs from your rating** in the same neutral tone, or **No set rating**, plus the Unverified pill); the **Evidence check** box (outcome reading, the supporting item, who reported it, the independent-support finding and the outcome evidence with hostname links and stale marks, labelled "Affects confidence only, never the rating"); the five source pills (rating, or "no cited fact" for an unproven one); the narrative. Collapsed, starting collapsed on every render and never persisted: **Fact behind each source rating**; **Declines reviewed: N found, M counted against the rating** (each observed-damage entry, whether it counted and why); **Forward threats** ("What could happen, not what has happened. Never changes the rating.", then each threat with what was seen, tripwire metric, value now and review level). Then the "Would lower it" and "Would raise it" lines, the evidence note as a warn-toned banner when present, and the footer "Advisory only. Never changes your rating or any score." An inconclusive row shows, instead of the single-pass body, two columns (stacked on mobile) with each pass's rating, reading, strongest source and supporting item and a one-line reason from the two readings. There is no Apply button and no "overall if applied" score.

## What it never does

- **Never writes `TickerMoat`** and has no path that could: the rating that scores changes only through `PUT /api/tickers/{t}/moat` and its confirm step.
- **Never triggers a score recompute**, never touches `TickerScore`, `weights_version`, `moat_multiplier` or `SCORE_FORMULA_VERSION`, and is not read by the Screener, the Watchlist, Momentum or Opportunities.
- **Never calls FMP.** The app makes no request for it; the data block is built from stored rows only (read-only).
- **Never feeds the tracked universe.** The table is `KEEP` in `data/ticker_data_registry.py` and is **not** in `MANUAL_DATA_MODELS` (a check is not owner-entered data and must not protect or admit a ticker).
- **Never applies to an ETF or fund.** The save script refuses a known ETF (the same check as the Moat PUT) and the ETF page has no Moat tab.

## The command flow (`/moat-check <ticker>`)

The command file `.claude/commands/moat-check.md` stays **thin**: it names the steps and points at [Moat criteria](moat-criteria.md); it does not embed the criteria.

1. **Run date.** Take today's date from the system (RUN_DATE). Nothing in the criteria is dated.
2. **Build the data block** with a small read-only script (`pipeline/moat_check_block.py`, opens the database `mode=ro`): ticker, company name, sector, industry, annual margins and a price-chart description. **Margins: net margin only** when the FMP `industry` is `Banks` or any `Banks - …`, `Insurance` or any `Insurance - …`, `Financial - Capital Markets`, or `Asset Management` or any `Asset Management - …`, or the ticker is one of the named card lenders AXP, COF, SYF, DFS, ALLY (they share `Financial - Credit Services` with the payment networks V, MA and PYPL, which an industry label cannot separate from them); **every other company, and any industry not seen before, gets gross and net margin** (payment networks, exchanges and data companies such as SPGI, CME and ICE, and `Investment - Banking & Investment Services` included). The rule is the constants `NET_MARGIN_ONLY_PREFIXES`, `NET_MARGIN_ONLY_INDUSTRIES` and `NET_MARGIN_ONLY_TICKERS` in `pipeline/moat_check_block.py`; to extend it add an exact label, a family prefix or a ticker there (with a test). The script also prints the cache dates it read (statement fiscal dates, last bar date) and the margin rule it applied to the screen; they are never written into the block, whose key set is fixed. **It contains no Moat rating, no Fathom score, no verdict and no Overall.** The set rating is never read by the command at any point before the passes finish.
3. **Two blind passes.** Two subagents run the same task independently, each given only the path to `docs/specs/moat-criteria.md`, the data block, RUN_DATE and its own output path, and told to read nothing else (the criteria's hard rule). Neither is given the set rating, the repo state or the other pass. The main session does not look at the set rating either.
4. **Save** with `cd backend && uv run python -m pipeline.moat_check_save <ticker> <pass1.json> <pass2.json> [<run_date>]`. The script validates both records against the criteria's output schema (all keys, enumerations, the five sources each with a fact or `null` + "unproven", `proof_basis`, no `tag`/`independent_support`/`rule_effects`; a rated source with no fact or an unproven one carrying a fact is refused). Two values are **derived in code, never rejected**: the overall `threat_level` (the highest level among the threats, Low with none) and `evidence_confidence` (forced to Low when `proof_basis` is `company_reported_only`). It then **reconciles in code** and appends one row. **Warnings, never refusals:** an empty prose field (`narrative`, `margins_note`, `would_lower`, `would_raise`, or an empty-string `evidence_note`) is saved as given and reported in the script's output, and so is a pass whose `checked_date` differs from `<run_date>` (the optional fourth argument), so a full research run is never thrown away over prose or a date. If either record is invalid in structure nothing is saved (no partial rows) and the command retries the failing pass once, then reports the failure.
5. **Report.** One line: ticker, status, check rating (or "inconclusive"), confidence. The agrees/differs comparison happens only on the card.

**Reconciliation lives in code (`data/moat_check.py::reconcile`), never in the prompt:**

| | Result |
|---|---|
| Both passes give the same rating | status `stable`, `rating` = that rating, detail columns = pass 1's |
| The ratings differ | status `inconclusive`, `rating` NULL, detail columns NULL (both passes stay in the JSON columns), confidence Low |
| Confidence | the lower of the two passes (Low < Medium < High) |
| `proof_basis` | `company_reported_only` if **either** pass says so, else `independent` |

## Table: `MoatCheck` (one row per run)

New model in `core/models.py`, created by `create_all` (the app has no migration tooling, see `core/db.py`). **History is kept: every run appends a row, none is replaced or deleted.** The card reads the newest row for the ticker (`checked_at` descending). Cost: about 22 KB a run (two passes), so a hundred tickers re-run four times is about 9 MB against a 1.4 GB database; a run costs about 14 web searches to redo, which is why the table is `KEEP` (never wiped) and why history is not overwritten. Index on `(ticker, checked_at)`.

| Column | Type | Meaning |
|---|---|---|
| `id` | int, primary key | |
| `ticker` | str, indexed | normalized |
| `checked_at` | datetime | when the row was saved |
| `criteria_version` | str | `moat-criteria-v5.2` |
| `status` | str | `stable` \| `inconclusive` |
| `rating` | str, nullable | `wide_moat` \| `narrow_moat` \| `no_moat`; NULL when inconclusive |
| `pass1_rating`, `pass2_rating` | str | each pass's rating |
| `evidence_confidence` | str | `High` \| `Medium` \| `Low` (reconciled) |
| `proof_basis` | str | `independent` \| `company_reported_only` (reconciled) |
| `threat_level` | str, nullable | pass 1's overall threat level when stable, else NULL |
| `source_ratings_json`, `source_facts_json`, `observed_damage_json`, `forward_threats_json` | text, nullable | pass 1's values when stable, NULL when inconclusive |
| `would_lower`, `would_raise`, `evidence_note` | text, nullable | pass 1's when stable, else NULL |
| `pass1_json`, `pass2_json` | text | the two validated records, with `threat_level` and `evidence_confidence` as derived in code |

There is no `tag` column and no stored reason for a difference with the set rating. Registry: `TableClass.KEEP` ("independent Moat check history, expensive to re-create"). Merging duplicate ticker spellings (`pipeline/merge_duplicate_ticker_identities.py`) gets a `TableMergeConfig` entry (no test enforces completeness there, so it is a manual step). Backups need nothing: `pipeline/backup_db.py` copies the whole file.

## API

One read-only endpoint, no write endpoint (v1):

- `GET /api/tickers/{ticker}/moat-check` returns the newest row for the ticker (query columns, the detail fields, `criteria_is_current`, `pass1` (pass 1's whole record, always: the outcome reading, evidence, narrative and sources exist only there) and, for an inconclusive row, `pass2` too; the nested parts are loosely typed on purpose so a row from a later criteria version still serves), or **JSON `null` when the ticker has never been checked** (the card's "Not checked yet"). It reads the database only. A history listing endpoint is deferred: history is stored, not served.

Rows are written only by `pipeline/moat_check_save.py`, which is not a cron job (no `CRON_JOB_NAMES` entry, no heartbeat). The settings allowlist may carry `Bash(uv run python -m pipeline.moat_check_save *)` to avoid a prompt per run; that is a personal setting, not part of the repo.

## Operating notes

- **Blindness is structural, not trusted.** The criteria tell the agent not to look for any other rating, and the command never puts the set rating in front of a subagent. The v5.1 test round was blind the same way (its data block held name, sector, industry, margins and a chart description only).
- **Empty prose.** A stored pass can have an empty `narrative` or note (it was saved with a warning); the card shows nothing for an empty prose field rather than a blank label.
- **Re-running** appends a row. A re-run on the same criteria version that gives a different answer is information, which is why history is kept.
- **Dev server.** Adding the model makes `uvicorn --reload` run `init_db()` on the real database, which creates the empty table. Take a manual backup before the model phase (see `backend/OPS_RUNBOOK.md`).
- **Tests** use an in-memory engine monkeypatched onto every module's `engine` (the conftest write guard blocks the real one).

## Build phases

1. **Table and persistence (done):** `MoatCheck` model, `data/moat_check.py` (schema validation, `reconcile`, append, latest), registry `KEEP`, merge entry; tests (validation, reconcile table above, history appends, latest, registry, backup, no `TickerMoat` write, ETF refusal). Full backend suite (shared models and registry).
2. **Read API (done):** schema and `GET /api/tickers/{t}/moat-check` returning null; endpoint tests.
3. **Scripts (done):** `pipeline/moat_check_block.py` (read-only block builder) and `pipeline/moat_check_save.py`; tests.
4. **Card (done):** types, `useMoatCheck`, the card inside the Moat tab, per the design system; full vitest, tsc and eslint.
5. **Command (not started):** `.claude/commands/moat-check.md`.
6. **Trial (not started):** `/moat-check` on one ticker; verify the saved row, the API output and the card's props through tests (no browser verification).

Each phase is planned, confirmed and committed separately (CLAUDE.md, Workflow rules).
