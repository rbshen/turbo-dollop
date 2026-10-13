# Independent Moat check

**Status: built (phases 1 to 5), run live on PM 2026-10-13 (canary, refusals and a full run passed).** The table, read API, block, prepare, save and finish scripts, the card, the `/moat-check` command (`.claude/commands/moat-check.md`), the two pass agents (`.claude/agents/moat-pass-1.md`, `moat-pass-2.md`) and their guard hook (`.claude/hooks/moat-pass-guard.py`) exist and are tested, and the live trial (phase 6) confirmed the guard's behaviour inside Claude Code (see "Confirmed in the live trial" under Enforcement). The criteria themselves are final and live in [Moat criteria](moat-criteria.md) (`moat-criteria-v5.2`).

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

1. **Run date.** `pipeline/moat_check_prepare.py` takes today's date from the system (RUN_DATE) and computes the 18-month stale cutoff itself (calendar-month arithmetic, the day clamped to the target month), and the command passes both to each pass explicitly, so a pass never does date arithmetic. Nothing in the criteria is dated.
2. **Prepare** with `uv run --directory backend python -m pipeline.moat_check_prepare <ticker>`, which first refuses anything that is not one ticker symbol, removes run folders over a day old, and **builds the data block** with the read-only block builder (`pipeline/moat_check_block.py`, opens the database `mode=ro`; an ETF or a ticker with no cached data is refused here, before anything is created): ticker, company name, sector, industry, annual margins and a price-chart description. **Margins: net margin only** when the FMP `industry` is `Banks` or any `Banks - …`, `Insurance` or any `Insurance - …`, `Financial - Capital Markets`, or `Asset Management` or any `Asset Management - …`, or the ticker is one of the named card lenders AXP, COF, SYF, DFS, ALLY (they share `Financial - Credit Services` with the payment networks V, MA and PYPL, which an industry label cannot separate from them); **every other company, and any industry not seen before, gets gross and net margin** (payment networks, exchanges and data companies such as SPGI, CME and ICE, and `Investment - Banking & Investment Services` included). The rule is the constants `NET_MARGIN_ONLY_PREFIXES`, `NET_MARGIN_ONLY_INDUSTRIES` and `NET_MARGIN_ONLY_TICKERS` in `pipeline/moat_check_block.py`; to extend it add an exact label, a family prefix or a ticker there (with a test). The script also prints the cache dates it read (statement fiscal dates, last bar date) and the margin rule it applied to the screen; they are never written into the block, whose key set is fixed. `moat_check_prepare` then creates `/tmp/moat-check/<TICKER>-<timestamp>/pass1/` and `pass2/`, each holding **a byte-identical copy of `docs/specs/moat-criteria.md` (`criteria.md`) and the block (`block.json`)**, probes the guard hook command of both agent files as the shell would run it (a denied path must exit 2, an own-folder path 0, the other pass's folder 2; a failed probe removes the folder and stops, exit 3), and prints `run_dir`, `run_date`, `stale_cutoff` and the screen-only cache dates. **It contains no Moat rating, no Fathom score, no verdict and no Overall.** The set rating is never read by the command at any point before the passes finish.
3. **Two blind passes.** The command starts the named agents `moat-pass-1` and `moat-pass-2` (never a fork, which would inherit the conversation) in parallel, each with the same fixed text: the ticker, RUN_DATE, the stale cutoff and its own folder. Each reads only its own `criteria.md` and `block.json`, researches the web as the criteria describe, and writes `out.json` in its folder. **Confinement is enforced, not asked for:** see "Enforcement" below. Neither pass is given the set rating, the repo state or the other pass, and cannot reach the other pass's folder. The main session does not look at the set rating either.
4. **Save** with `cd backend && uv run python -m pipeline.moat_check_save <ticker> <pass1.json> <pass2.json> [<run_date>]`. The script validates both records against the criteria's output schema (all keys, enumerations, the five sources each with a fact or `null` + "unproven", `proof_basis`, no `tag`/`independent_support`/`rule_effects`; a rated source with no fact or an unproven one carrying a fact is refused). Two values are **derived in code, never rejected**: the overall `threat_level` (the highest level among the threats, Low with none) and `evidence_confidence` (forced to Low when `proof_basis` is `company_reported_only`). It then **reconciles in code** and appends one row. **Warnings, never refusals:** an empty prose field (`narrative`, `margins_note`, `would_lower`, `would_raise`, or an empty-string `evidence_note`) is saved as given and reported in the script's output, and so is a pass whose `checked_date` differs from `<run_date>` (the optional fourth argument), so a full research run is never thrown away over prose or a date. If either record is invalid in structure nothing is saved (no partial rows): the script validates **both** passes and prints every problem of both, one per line, each starting `pass 1:` or `pass 2:` (an unreadable or missing `out.json` is named the same way), and exits 2. The command then restarts **only the pass(es) named, once**, with the same text plus those problem lines for that pass, and saves again; if it still fails it prints the problems and keeps the run folder. Exit 1 (table missing) and 3 (ETF) stop the run and keep the folder.
5. **Report and clean up.** One line: ticker, status, check rating (or "inconclusive"), confidence, then any warnings. The agrees/differs comparison happens only on the card. `moat_check_finish <run_dir>` then deletes the run folder; it refuses any path that is not a run folder directly under `/tmp/moat-check/` (the base itself, a file such as `guard.log`, a symlink, `..`, a link out). A failed run's folder is kept and removed by the next `moat_check_prepare` once it is a day old.

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

## Enforcement (why a pass cannot see the set rating)

Decision 2026-10-12 (docs/decisions.md): restricted subagents plus a guard hook, plus per-pass folders outside the repo. The user-level settings of the owner already allow `Read(//home/**)`, so a general subagent could read the repo, the database and `backend/.env` without a prompt; an instruction alone ("read nothing else") is what the v5.1 round relied on.

- **The agents** (`moat-pass-1`, `moat-pass-2`, identical but for the pass number): `tools: Read, Write, WebSearch, WebFetch, ToolSearch` (no Bash, Grep, Glob, Edit or Agent), `model: sonnet`, `omitClaudeMd: true`. A subagent starts with an empty conversation.
- **The guard** (`.claude/hooks/moat-pass-guard.py <n>`, a `PreToolUse` hook in each agent's frontmatter, matcher `*`): a Read may name only `criteria.md`, `block.json` or `out.json` in `/tmp/moat-check/<run>/pass<n>/`, and a Write only `out.json` there (paths resolved with `realpath`; relative paths, `..`, symlink escapes, the other pass's folder, the repo, the database and the home directory are denied). WebFetch is allowed only to an http(s) URL on port 80 or 443 with a dotted host name: `file:` and other schemes, `localhost`, bare names, IP literals in any spelling, `*.local`, `*.lan`, `*.internal` and similar, and `user@` URLs are denied (the app listens on `0.0.0.0:8002`, and `GET /api/tickers/<t>/moat` answers there). Every other tool is denied. It fails closed: exit 2 for anything it does not recognise and for any crash, because Claude Code treats any other non-zero exit as a non-blocking error and lets the call through. A blocking hook beats allow rules.
- **The audit trail:** every decision is appended to `/tmp/moat-check/guard.log` (capped at about 1 MB); `MOAT_GUARD_LOG_DIR` moves only that log (the tests use it). A text-file call that leaves no log line means the hook did not run for it; that red flag applies to text files only (see "Known gaps" below for the binary-file exception).
- **Preflight:** `moat_check_prepare` runs the hook command of both agent files before the passes start, which catches a missing `python3` or a broken command string (exit 127 would otherwise fail open). It cannot prove Claude Code calls the hook; the phase 6 canary proved it (below).
- **Confirmed in the live trial (PM, 2026-10-13):**
  - The hook fires inside the named agents: every allowed and denied call of the canary and of both passes has a `guard.log` line carrying the agent id, and the log matches the subagent transcripts call for call.
  - `file_path` (Read, Write) and `url` (WebFetch) are the correct field names: the own-folder read was allowed, and a read of the other pass's folder, a Write of `criteria.md`, a repo write, port 8002 and `CLAUDE.md` were denied.
  - The `uv run --directory backend python -m pipeline.moat_check_*` commands ran with no permission prompt.
  - ToolSearch loads WebSearch and WebFetch for the agents (ToolSearch is in their tool list for this).
  - One check took about 4.5 minutes, with about 15 searches and 14 fetches across both passes (7 and 7 fetches, 7 and 8 searches).
  - Bash, Grep and Glob are not in the agents' tool lists, so they are unavailable, not merely denied.
- **Known gaps (two):** (a) the hostname risk below. (b) **Binary files.** The Read tool rejects a binary file such as `backend/fathom.db` before the PreToolUse hook runs, so a database read leaves no `guard.log` line. It is still blocked: Read refuses it itself, and the guard also denies it when called directly (exit 2). The no-log-lines red flag therefore applies to text files only.
- **Residual risks, accepted:** (1) a hostname that resolves to this machine (for example `127.0.0.1.nip.io`) passes the guard, which judges the spelling of the host and not what DNS returns, so the guard alone does not stop it, but since 2026-10-13 the app listens on 127.0.0.1 only and its request guard answers 400 to any Host other than localhost, 127.0.0.1 or [::1] (docs/decisions.md, 2026-10-13), so such a fetch gets no moat rating back; (2) the guard works only if Claude Code runs project-level agent hooks (the workspace must be trusted, hooks not disabled); the phase 6 canary showed it does here, and `moat_check_prepare`'s preflight does not re-prove it each run, so a run whose passes leave no text-file log lines is not to be trusted; (3) the model's own training knowledge is not something a guard can remove. Had the canary shown the hook inactive, the fallback would be one headless `claude -p` process per pass with its folder as working directory and user settings excluded; it is not built and was not needed.

## Operating notes

- **Blindness is structural, not trusted.** The criteria tell the agent not to look for any other rating, the command never puts the set rating in front of a subagent, and the guard (above) makes the instruction mechanical. The v5.1 test round was blind by instruction only (its data block held name, sector, industry, margins and a chart description only; its transcripts show every pass read just its two files).
- **Empty prose.** A stored pass can have an empty `narrative` or note (it was saved with a warning); the card shows nothing for an empty prose field rather than a blank label.
- **Re-running** appends a row. A re-run on the same criteria version that gives a different answer is information, which is why history is kept.
- **Dev server.** Adding the model makes `uvicorn --reload` run `init_db()` on the real database, which creates the empty table. Take a manual backup before the model phase (see `backend/OPS_RUNBOOK.md`).
- **Tests** use an in-memory engine monkeypatched onto every module's `engine` (the conftest write guard blocks the real one).

## Build phases

1. **Table and persistence (done):** `MoatCheck` model, `data/moat_check.py` (schema validation, `reconcile`, append, latest), registry `KEEP`, merge entry; tests (validation, reconcile table above, history appends, latest, registry, backup, no `TickerMoat` write, ETF refusal). Full backend suite (shared models and registry).
2. **Read API (done):** schema and `GET /api/tickers/{t}/moat-check` returning null; endpoint tests.
3. **Scripts (done):** `pipeline/moat_check_block.py` (read-only block builder) and `pipeline/moat_check_save.py`; tests.
4. **Card (done):** types, `useMoatCheck`, the card inside the Moat tab, per the design system; full vitest, tsc and eslint.
5. **Command (done, not run live):** `.claude/commands/moat-check.md`, the two agent files, the guard hook, `moat_check_prepare` and `moat_check_finish`, pass-numbered validator problems.
6. **Trial (done, 2026-10-13):** canary, refusals (an ETF, an invalid ticker string) and a full run on PM passed; PM saved as a stable Wide row, Low confidence, `company_reported_only` proof. The card's props are not browser-verified (CLAUDE.md, Workflow rules).

Each phase is planned, confirmed and committed separately (CLAUDE.md, Workflow rules).
