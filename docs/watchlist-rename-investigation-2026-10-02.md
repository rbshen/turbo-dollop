# Watchlist rename W1-W5 -> E<number> + "ETF": Phase 1 investigation (2026-10-02)

Task A of two (Task B, the ETF page, follows). Read-only investigation: no code or DB changes. Live DB was
opened read-only (`mode=ro`). Context: `docs/etf-page-investigation-2026-10-01.md`.

## Summary

- A watchlist is stored as a row with an integer `id`; the name is a plain unique column. **Everything that
  references a list does so by `id`** (`WatchlistTicker.watchlist_id`, `SavedScreenerFilter.watchlist_id`,
  frontend localStorage sort key). No signal table, cache, setting or alert stores a list name. **The rename is
  five `UPDATE watchlist SET name` statements.** Contents, history and settings are untouched by construction.
- **There is no 5-list limit anywhere** (no DB constraint, no API check, no UI cap). The "5" exists only as the
  regex `^W[1-5]$`. Lists with other names (`W6`, custom) are simply never matched by the jobs. The only
  enforced cap is 100 tickers per list (`WATCHLIST_CAPACITY`), which is separate and still applies to a list
  named "ETF" unless exempted (decision 2 below).
- The regex is defined **four times** (three nightly jobs + one backfill script), not in `data/watchlists.py`
  as CLAUDE.md claims. Only the union helper is shared.
- **No collisions**: no list named `E<number>` or `ETF` exists in the live DB.
- **No external consumers found** on the VPS (no other repo, service, cron or script reads Fathom's lists).
- **The UI label "On watchlist W3" does not exist.** The user-visible W-strings are listed in section 1.
- Load: 105 tickers across W1-W5 (zero overlap), ~3-4 min/night of technical jobs. The jobs are CPU-bound
  (~1.7-2.4 s per ticker for the three jobs combined), so **runtime, not FMP rate limit, is what an unbounded
  number of lists hits first** (BB+RSI overruns its 5-minute cron slot at roughly 235-510 monitored tickers).
- Two findings unrelated to the rename but relevant to the tier move (section 5): the existing nightly chain
  already overlaps two 220 req/min jobs, and `pipeline.backup_db` would currently refuse to run for lack of
  free disk.

## 1. Every reference to the W1-W5 pattern or "W" names

(`git ls-files`, excluding `node_modules`; line numbers as of commit `d8a3f0e`.)

### Pattern definitions (the four duplicated copies)

| File:line | Content |
|---|---|
| backend/pipeline/nightly_liquidity_zone_calculation.py:49 | `WATCHLIST_NAME_PATTERN = re.compile(r"^W[1-5]$")` (used :69, :74, :81) |
| backend/pipeline/nightly_entry_signal_calculation.py:53 | same (used :74, :77, :80) |
| backend/pipeline/nightly_warren_signal_calculation.py:64 | same (used :86, :89, :92) |
| backend/pipeline/backfills/backfill_fmp_daily_bars.py:71 | same (used :82). Already-run historical script |
| backend/data/watchlists.py:26-52 | `list_tickers_across_watchlists(session, name_pattern)`: the shared union helper; takes the pattern as an argument. Docstring (:33-34) says "^W[1-5]$ ... add a W3/W4/W5 later" and names only two callers (three actually use it plus the backfill) |

### Backend comments, docstrings and strings that name W1-W5 (no logic)

- backend/core/cron_health.py:131, :134, :137: **UI-visible** Settings > Scheduled Jobs descriptions
  ("BB+RSI (2h) entry signal, W1-W5 watchlists", "Support/resistance zone detection, W1-W5 watchlists",
  "Warren RSI/ADX/WVF (2h) entry signal, W1-W5 watchlists").
- backend/core/main.py:582, :597 (comments on the cache-only `/entry-signal` and `/liquidity-zones` endpoints).
- backend/core/models.py:232, :234, :386, :798, :816, :829 (docstrings/comments).
- backend/core/schemas.py:1069, :1072, :1242, :1335, :1498, :1505 (comments).
- backend/data/entry_signal_data.py:7, :38, :171, :182; liquidity_zone_data.py:7, :42, :143, :162;
  warren_signal_data.py:51, :270; chart_data.py:432 (comments/docstrings).
- backend/pipeline/nightly_entry_signal_calculation.py:2; nightly_liquidity_zone_calculation.py:2;
  nightly_warren_signal_calculation.py:2, :13, :28; nightly_trend_calculation.py:103 (module docstrings and a
  comment; the "(up to 100 ..." text in the first lines of the three jobs is also stale-prone).
- backend/pipeline/backfills/backfill_fmp_daily_bars.py:22 (docstring).
- backend/crontab.txt:47, :52, :59 (comments only).

### Frontend

User-visible strings (these are the only UI labels that name W lists; **no "On watchlist W3" label exists**):

- frontend/components/technical/BbRsiEntrySignalCard.tsx:12: "...only runs nightly for tickers in the "W1" or "W2" watchlists." (already stale: says W1/W2 only)
- frontend/components/technical/LiquidityZonesCard.tsx:26: same "W1" or "W2" text (already stale)
- frontend/components/technical/WarrenSignalCard.tsx:12: `in a "W1"-"W5" watchlist`
- frontend/components/screener/TechnicalFilters.tsx:61: "...only ever match tickers on a watchlist named W1 through W5."
- frontend/components/settings/LiquidityZoneSettingsForm.tsx:116: intro "computed nightly for watchlists named W1 through W5 only"

Comments only: frontend/lib/api/types.ts:627, :632, :1318, :1512; lib/hooks/useEntrySignal.ts:9,
useLiquidityZones.ts:9, useWarrenSignal.ts:9; lib/screenerFilters.ts:144, :149; app/watchlist/page.tsx:186-187
(says "unbounded number of watchlists", consistent with there being no list-count cap).

Test fixtures using `"W1"`/`"W2"` as arbitrary names (cosmetic, no logic tied to W): app/screener/page.test.tsx:100;
app/watchlist/page.test.tsx:17, :26, :58-69; components/screener/SidebarSections.test.tsx:178, :190;
components/watchlist/WatchlistTable.test.tsx:21, :150-209.

`/styleguide` (excluded from this task per instructions): app/styleguide/page.tsx:591-593;
ScreenerSidebarMock.tsx:171-172 and its test :109, :114; SettingsMocks.tsx:216.

### Backend tests

- tests/test_watchlists.py:9 (its own copy of `PATTERN = re.compile(r"^W[1-5]$")`, so the test does not exercise
  the production constant), :32-83 (W1/W2/W3/W6 seeds; :59 "W6 out of 1-5 range must not match").
- tests/test_nightly_entry_signal_calculation.py:71-173; test_nightly_liquidity_zone_calculation.py:85-275;
  test_nightly_warren_signal_calculation.py:71-144 (seed W1, W2, W3, W6; W6 asserted excluded).
- tests/test_non_us_purge.py:54 (`Watchlist(name="W1")`, fixture only); tests/test_ticker_score.py:417 (comment).
- `tests/test_cron_wiring.py` has no W reference (it checks job names/cadence only; the description strings in
  `JOB_METADATA` are not asserted).

### Docs

- CLAUDE.md:91 (100-ticker cap), :93 (the W1-W5 paragraph).
- docs/specs/liquidity-zones.md:110, :111, :119, :120, :135, :136; docs/specs/warren-signal.md:4, :36, :159.
- docs/etf-page-investigation-2026-10-01.md:19, :121, :122, :131, :132, :134, :202, :235 (historical; leave).
- docs/claude-md-restructure-plan.md:26, :43 (historical plan; leave).
- docs/archive/ (21 hits in CLAUDE.original.md and claude-md-history-technical-signals.md; history, leave).
- backend/OPS_RUNBOOK.md: no W-list references.
- docs/decisions.md, docs/design-system*.md: no W-list references.

## 2. How lists are stored; what a rename must update; external consumers

Schema (live DB, `sqlite_master`):

```
watchlist(id PK, name VARCHAR NOT NULL UNIQUE [uq_watchlist_name], sort_field, sort_direction, created_at, updated_at)  + ix_watchlist_name
watchlistticker(id PK, watchlist_id FK->watchlist.id, ticker, added_at, UNIQUE(watchlist_id, ticker))
```

- **Name is a mutable attribute; id is the key.** The rename API already exists (`PUT /api/watchlists/{id}`,
  with a 409 on duplicate name), so the app already treats renames as ordinary.
- References **by id** (unaffected by a rename): `WatchlistTicker.watchlist_id`; `SavedScreenerFilter.watchlist_id`
  (a discrete column, per its docstring; 0 saved filters reference a list in the live DB); frontend
  localStorage sort key `fathom-watchlist-sort-<id>` (app/watchlist/page.tsx:24); the Screener's watchlist
  filter passes `watchlistId`.
- References **by name**: only the nightly jobs' regex at run time, plus UI strings. Signal and zone tables
  (`TechnicalEntrySignal`, `TechnicalEntrySignalEvent`, `WarrenSignalEvent`, `LiquidityZoneAnalysis`) are keyed
  by ticker (+ signal type/timeframe) and **carry no list name**. `CronRunLog` stores job names only. No
  setting (`LiquidityZoneSettings`, `WeinsteinSettings`, data groups) references a list.
- So a rename must update exactly: `watchlist.name` (5 rows) and the strings in section 1. History is retained
  (events, zones, signals are per ticker and the tickers do not move).
- Side effect to be aware of: matching is by name **at run time**. If a monitored list is renamed to something
  else, the next nightly run no longer reaches its tickers and `sweep_stale_*` clears their readings after
  `STALE_AFTER_DAYS` (7). That is the existing behavior for W lists too.
- **External consumers on the VPS: none found.** Searched `options_tracker`, `ibkr_validation`, `warren_strategy`,
  `stock-scanner`, `fmp-2h-check`, `ubiquitous-fiesta`, `scratch` for `fathom`, `api/watchlists`, `watchlist`,
  `fathom.db`: only prose mentions (options_tracker/CLAUDE.md references Fathom's `bin/` pattern;
  stock-scanner/zigzag.py uses "watchlist" as a word; scratch/ reports quote the W1-W5 universe). The user
  crontab is Fathom-only (no other jobs); systemd runs no app services (only cron, ssh, chrony, etc.). The one
  thing I cannot see from here is a client on another machine calling the HTTP API; nothing on this box does.

## 3. Where the 5 is enforced; other names today

- DB: no constraint beyond `UNIQUE(name)`. API: `POST /api/watchlists` (main.py:947-953) and `PUT` (:956-968)
  validate only name uniqueness and `WatchlistName` (strip, 1-100 chars; schemas.py:1129). UI: create flow
  (`AddToWatchlistButton`, `WatchlistNameEditor`) has no count cap (maxLength 100 only).
- The "5" lives solely in `^W[1-5]$`. Names that do not match are **excluded from the jobs** (full match, so
  `W6`, `W10`, `w1`, `W1 ` are all out). They still work as ordinary lists everywhere else (Watchlist page,
  Screener filter, and their tickers still enter the full-universe jobs, see section 6).
- Live DB today: `W1`-`W5` plus two non-matching lists, `N scores passed` (id 11, 33 tickers) and
  `W score passed` (id 10, 50 tickers). Both stay unmonitored. The migration must match `W[1-5]` exactly (full
  match), so it cannot touch `W score passed`.
- The one enforced limit is **100 tickers per list** (`WATCHLIST_CAPACITY`, main.py:979, enforced in
  `watchlist_add_ticker` :993-1010 and bulk add :1013-1028). Not part of the requested change, but relevant: the
  "ETF" list "holds all ETFs".

## 4. Collision check (live DB, read-only)

```
id  name                  tickers
10  W score passed        50
11  N scores passed       33
24  W1                    19
25  W2                    34
26  W3                    23
27  W4                    15
28  W5                    14
```

No `E<number>` and no `ETF`. 135 distinct tickers across 188 membership rows. W1-W5 hold 105 distinct tickers
(19+34+23+15+14 = 105, so **no overlap between them**; matches the 105 in the 2026-10-01 job logs). W1-W5 were
created 2026-09-15 12:00:15 (sort_field `overall_score`, desc).

## 5. Load, FMP calls, runtime, rate-limit headroom

Real runs, 2026-10-01 (all 105 tickers, 0 failures; logs and `CronRunLog`):

| Job (UTC cron slot) | Run time | Per ticker | Slot to next job |
|---|---|---|---|
| LP zones 00:15 | 8.4 s | ~0.08 s | 5 min |
| BB+RSI 00:20 | 61.6 s (127.5 s the night before, 100 tickers) | 0.59-1.28 s | 5 min |
| Warren 00:25 | 111.3 s (103.1 s the night before) | ~1.0-1.1 s | 10 min (heatmap 00:35) |

Note the 2026-10-01 runs were at 02:15-02:26 server time: the move to 00:15-00:25 (commit `ba06d21`) takes
effect from the next nightly cycle, and the installed `crontab -l` already shows the new times.

**Per list** (combined three jobs, 1.7-2.4 s/ticker): W1 (19) ~32-46 s, W2 (34) ~57-82 s, W3 (23) ~39-56 s,
W4 (15) ~25-36 s, W5 (14) ~24-34 s. Total ~3-4 min. The jobs run per **union**, not per list, so a list's cost is
just its tickers.

**FMP calls** (these three jobs do not log call counts; figures derived from the code, `clients/daily_bar_sources.py`,
`technical_sources.py`, not measured):
- LP: reads daily bars through the shared cache; the 00:05 Weinstein job already tops it up for the full
  universe, so LP makes ~0 calls of its own (8 s runtime confirms nothing is fetched).
- BB+RSI and Warren share one 60m cache row per ticker (`FMPTechnicalSource` reads through
  `get_or_fetch_bars_batch`); whichever runs first does the live fetch. Steady state **~1 `/historical-chart/1hour`
  call per ticker per night** (3-day overlap fetch; +1 if FMP restated history). A *newly* monitored ticker costs
  a full 2-year paged fetch once (~9 pages per the code comment on `INTRADAY_MAX_PAGES`).
- So the 105 monitored tickers cost **~105 calls/night**, i.e. under a minute of even Starter quota.
- Everything else (trend, corporate events 2/ticker, price-target 1/ticker, last-close, fundamentals ~25 calls/ticker
  per 7 days) runs on the full ~582-ticker universe, which already includes every watchlisted ticker on
  *any* list (`load_full_tracked_universe`), so putting a ticker on an E list adds universe load only if the
  ticker was not already known (~8-9 calls/night all-in for a new ticker).

**Observed whole-chain volumes** (2026-09-30 / 10-01): fundamentals fetch 223 / 2,626 calls (324 s / 2,673 s);
price-target 581-582 calls (~10 min); corporate events 1,162-1,165 calls (~2-3 min).

**Rate-limit headroom for a lower tier.** Tier table in code (`FMP_PLAN_REQUESTS_PER_MIN`): Starter 300,
Premium 750, Ultimate 3000/min; the live DB plan is still `Ultimate`. The bar jobs pace to 50% of the plan rate
(`FMP_RATE_FRACTION`) with concurrency 10: Starter 150/min, Premium 375/min.
- **E-list technical jobs are not rate-limit-bound.** Their steady state is ~1 call per ticker; even 1,000
  monitored tickers is ~1,000 calls/night (~7 min of fetch at Starter's paced 150/min, ~3 min at Premium).
  They are CPU-bound (1.7-2.4 s/ticker), which keeps the call rate well under the pace.
- **Runtime is the first thing unbounded lists break**: BB+RSI overruns its 5-min slot at ~235-510 monitored
  tickers (300 s / 1.28-0.59 s); Warren overruns its 10-min slot at ~565. Cron does not wait for the previous
  job, so an overrun means overlapping processes, each with its own in-process pacer, so their request rates
  add (Starter 300/min is shared by all of them). The Warren spec already extrapolates "~9 minutes at 500
  tickers" (`docs/specs/warren-signal.md:36`) and notes the 15-minute window. Tickers past those counts need
  either wider slots or a per-job time budget; not part of this change, but the **"no upper limit" requirement
  should be documented as bounded by cron slot width in practice**.
- **Existing issue, independent of E lists, that the tier move exposes**: `nightly_fundamentals_fetch.py:75` and
  `nightly_price_target_snapshot.py:59` each hardcode `TARGET_REQUESTS_PER_MINUTE = 220` (73% of Starter's 300) and
  are not plan-aware (unlike the bar jobs). On 2026-10-01 they overlapped: fundamentals 02:55-03:39 and
  price-target 03:10-03:19 ran concurrently, ~440 req/min combined, which already exceeds Starter 300/min and is
  under Premium 750. Worth fixing as part of the tier move (separately from this task).
- **Existing issue, disk**: `/` has 1.4 GB free (94% used) and `backend/backups/` holds 1.8 GB. `pipeline.backup_db`
  refuses to start unless free space >= 1.25 x the DB size (`BACKUP_FREE_SPACE_FACTOR`); the DB is 1.31 GB, so it
  needs ~1.64 GB and by its own check **would refuse at today's 1.4 GB free** (not run, computed from the code).
  This matters for the migration's backup step (section 7).

## 6. Stock-only assumptions that break or waste calls when a list contains ETFs (flag only)

Technical jobs (the three affected jobs) are price-only and ETF-safe in principle: LP, BB+RSI, Warren read OHLCV.
Not exercised against an ETF in this investigation (the earlier ETF investigation reports 1hour bars work).

Wasteful for ETFs once they sit on **any** list (the universe includes every watchlisted ticker; not specific to
E lists):
- `nightly_fundamentals_fetch`: no ETF skip; ~25 FMP calls per ETF per 7 days, all empty
  (`docs/etf-page-investigation-2026-10-01.md:111`).
- `nightly_price_target_snapshot`: 1 call per ticker per night; the job already logs 8-9 failures nightly, cause
  not investigated here. `nightly_corporate_events`: 2 calls per ticker nightly (earnings/dividends may be
  legitimately non-empty for ETFs, dividends yes).
- `nightly_score_recompute`: cache-only, computes empty-score rows for ETFs (no FMP cost).
- Watchlist page `_consensus_rating`: one live `/grades-consensus` call per stale ETF per page view.
- Rough cost of a 50-ETF "ETF" list: ~50 x (25/7 fundamentals + 1 price target + 2 events) ~ 330 mostly-empty calls/night.
- Two ETFs (SPY, TECL) are already in `TickerScore` with `is_etf=1`, so this is already happening at small scale.

Also: the `ETF` list will be subject to the 100-ticker cap unless exempted (decision 2).

## 7. Proposed design

### 7.1 One shared rule (backend)

In `backend/data/watchlists.py` (already the shared home, already imported by all three jobs and the backfill):

```python
# A watchlist is "monitored" (read by the nightly LP / BB+RSI / Warren jobs) when its name is E<positive integer>
# or exactly "ETF". Case-sensitive, full match, no leading zeros: E1, E6, E10 yes; E0, E01, e1, ETFs, W1 no.
MONITORED_WATCHLIST_PATTERN = re.compile(r"E[1-9][0-9]*|ETF")

def is_monitored_watchlist_name(name: str) -> bool: ...
def list_monitored_watchlists(session) -> list[Watchlist]: ...
def list_monitored_tickers(session) -> tuple[list[str], list[str]]:   # (deduped tickers, matched names)
```

- `list_tickers_across_watchlists(session, pattern)` is replaced by `list_monitored_tickers(session)`; the three
  jobs and the backfill drop their `WATCHLIST_NAME_PATTERN` and `import re`. Log messages use
  `MONITORED_WATCHLIST_PATTERN.pattern`.
- Iteration order: currently ascending lexical name (`E1, E10, E2`); only affects processing order, but a
  natural sort (`E1, E2, ..., E10, ETF`) is cheap and makes logs readable. Dedupe stays first-seen.
- A test asserts the three jobs and the backfill reference the shared helper (guards against a fifth copy, like
  `test_cron_wiring` guards drift).
- Optional, flagged: `WatchlistNameEditor` and the create flow could show a one-line hint ("E<number> and ETF
  lists are monitored nightly"); today renaming a monitored list silently stops monitoring (section 2). Not
  required.

### 7.2 Frontend

- The five user-visible strings in section 1 become one wording, from a single constant in a small
  `frontend/lib/monitoredWatchlists.ts` ("a watchlist named E<number> (E1, E2, ...) or ETF"). The two stale
  "W1 or W2" cards are fixed by the same change. Settings > Scheduled Jobs text changes via `cron_health.py:131-137`.
- Frontend does **not** need the regex (no logic keyed on name), so no client-side matching function.
- `/styleguide` untouched, per instructions. Frontend test fixtures named W1/W2 can stay (arbitrary names).

### 7.3 Migration W1-W5 -> E1-E5 (idempotent, reversible, backup first)

New `backend/pipeline/rename_monitored_watchlists.py`, same conventions as `merge_duplicate_ticker_identities.py`
(`--dry-run`, run via `-m`, explicit `init_db()`, logged), plus `--rollback`. **Not** a cron job, so no
`CRON_JOB_NAMES`/crontab entry needed.

1. **Preflight (read-only)**: map `W1..W5 -> E1..E5` by exact name. Abort with a clear message if any target
   name already exists while its source also exists (collision); today none do.
2. **Backup first.** Two layers:
   - *Logical backup (always, automatic)*: dump `watchlist`, `watchlistticker`, `savedscreenerfilter` to
     `backend/backups/watchlist_rename_<ts>.json` (a few KB; this is everything the rename can touch) and verify
     it re-reads with matching row counts before writing anything. This is what rollback restores from.
   - *Full DB backup*: `pipeline.backup_db.create_backup` (sqlite online backup, gzip, ~150 MB) is the "DB backup
     taken first" the task asked for, **but at today's 1.4 GB free it will refuse** (section 5). The script calls
     it first and, if it refuses for disk space, stops with that message rather than skipping silently
     (`--skip-full-backup` available only with an explicit flag). Last good full backup:
     `fathom_20261001_033003.db.gz` (2026-10-01 03:33). See decision 3.
3. **Rename** in one transaction: `UPDATE watchlist SET name='E<n>', updated_at=now WHERE name='W<n>'`
   (id, sort prefs, ticker rows, saved filters, `created_at` unchanged). Commit, then re-read and assert: same ids,
   same ticker counts per id, 0 `W[1-5]` rows left.
4. **Idempotent**: a re-run finds no `W[1-5]` names and makes zero writes (a run with only some lists renamed
   finishes the rest). Never touches `W score passed`, `N scores passed`, `W6`, etc.
5. **Rollback**: `--rollback` renames `E1..E5 -> W1..W5` (by id, from the logical backup's id->name map, so it
   never renames an unrelated list a user later created as `E7`). Manual rollback is one SQL statement per
   list; full-DB restore remains the last resort.
6. **Timing**: run when no nightly job is mid-flight (jobs read list names once at start; a rename between runs
   is atomic and harmless). Deploy the code change and the migration in the same window before the 00:15 UTC
   slot: if code ships without the migration (or vice versa) the three jobs log "No watchlist matching ... exists",
   process nothing, and the sweep only clears readings after 7 days, so a short mismatch costs one night at most.
7. Verification on the live DB (read-only): `SELECT id,name,(SELECT count(*) ...)` equals the table in section 4
   with W1-W5 renamed; then run the three jobs' log lines the next morning (`... for 105 tickers across ['E1', ...]`).

### 7.4 Tests (targeted)

- New `tests/test_monitored_watchlists.py`: pattern accepts `E1, E6, E10, E999, ETF`; rejects `E0, E01, e1, E,
  E1 , ETFS, ETF2, EE1, E-1, W1, W6, "W score passed"`; helper returns dedupes across lists (incl. "ETF"),
  natural order, names list.
- Update `test_watchlists.py` (use the production constant, not a local copy), and the three nightly-job tests
  (seed `E1/E2/E3/E6/E10/ETF`; assert E6/E10/ETF included, `W1` now excluded). `test_non_us_purge`/`test_ticker_score`
  need no change (fixture name/comment only).
- New migration tests on an in-memory engine (per CLAUDE.md convention, patched on every module): renames W1-W5
  keeping ids, tickers, `SavedScreenerFilter` link and sort prefs; idempotent re-run = 0 writes; collision aborts
  with nothing changed; rollback restores names; `W score passed`/`W6` untouched; logical backup round-trips.
- Frontend: `tsc` + `eslint` + the tests of the five touched components (none assert the old strings today).
- Preliminary view on the full suite: **not required**. No schema, scoring, endpoint-shape, data-group or cache
  change; the targeted set (the above plus `test_cron_wiring.py` and `-k watchlist`) covers every touched path.
  I will confirm before skipping.

### 7.5 Docs to update

CLAUDE.md (Watchlists section: new rule and shared helper location; removes the false "list_tickers_across_watchlists
holds the pattern" claim and adds Warren to the consumers), `docs/specs/liquidity-zones.md`
(:110, :111, :119, :120, :135, :136), `docs/specs/warren-signal.md` (:4, :36, :159), `backend/crontab.txt` comments
(:47, :52, :59, then reinstall check: `crontab crontab.txt` from `backend/` and `crontab -l` vs file, per CLAUDE.md,
although comment-only edits change nothing at runtime), the code comments in section 1, `backend/OPS_RUNBOOK.md`
(new short section: the migration, verification, rollback). Historical docs (archive, ETF investigation,
restructure plan) are left as written.

### 7.6 Inconsistencies with docs/specs found

1. CLAUDE.md:93 says "The pattern match lives in `data/watchlists.py::list_tickers_across_watchlists`"; the regex
   actually lives in four other files, the helper takes it as a parameter. (The ETF investigation noted this.)
2. CLAUDE.md:93 and the `watchlists.py` docstring name only BB+RSI and LP as consumers; Warren
   (`nightly_warren_signal_calculation.py`) uses the same helper and pattern.
3. CLAUDE.md:93 "a user can add a W3/W4/W5 later": all five already exist (created 2026-09-15).
4. The BB+RSI and LP empty-state cards say "W1 or W2"; Warren's says "W1-W5". Three different statements of one rule.
5. Job-module docstrings quote "up to 100 tickers" / "98-ticker union"; the union is now 105 and the spec's
   "500-ticker worst case ~9 min" for Warren does not account for the 5/10-minute slot widths in
   `crontab.txt` (section 5).
6. The task text mentions a UI label "On watchlist W3"; no such label exists in the code.

## Decisions needed from you

1. **Pattern strictness.** Proposed: `E[1-9][0-9]*` or exactly `ETF`, case-sensitive full match (so `E0`, `E01`,
   `e1`, `etf` are NOT monitored). Alternative: case-insensitive. Default if you do not say: strict as above.
2. **100-tickers-per-list cap on the "ETF" list.** The cap stays for every list as is. Do you want "ETF" exempt (or a
   higher cap)? It is a Task B concern, but the shared helper is where an exemption would naturally live.
3. **Full-DB backup vs disk.** A fresh full backup cannot be taken until space is freed (needs ~1.64 GB free, 1.4 GB
   now; `backend/backups/` is 1.8 GB). Options: (a) you free space/prune old backups and the script's full backup
   runs; (b) rely on the logical 3-table backup plus the 2026-10-01 03:33 full backup (the rename touches only
   `watchlist.name`). Default if you do not say: (b), with the script refusing unless run with `--skip-full-backup`.
4. **Hint on rename** (7.1 optional) and **natural sort order**: include or skip. Default: natural sort yes, rename hint no.
5. Out of scope here, but you may want tickets: plan-aware pacing for the two 220 req/min jobs before the tier
   change, and cron slot widths for the technical jobs if monitored tickers grow past a few hundred.
