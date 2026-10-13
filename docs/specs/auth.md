# Login accounts, roles and viewer rules (security step 3, 2026-10-13)

Fathom is private: an SSH tunnel to `http://localhost:3100`, no TLS, no public access (docs/decisions.md, 2026-10-13, "lockdown"). Step 3 puts a login in front of the
backend so that more than one person can use the tunnel without every one of them being the owner. **The backend is built and enforced (step 3); the frontend login, 401/403 handling and viewer UI are built too (step 4, 2026-10-13, "Frontend" below).** Decisions already made and not revisited here: no universe cap, no public sign-up, accounts are created by an admin through the CLI
only, and settings, watchlists and saved views stay global (no per-user data).

## Accounts

- Tables `user`, `usersession`, `auditlog` (`core/models.py`, created by `create_all`; `init_db()` creates them and **never seeds a user**, because cron jobs call it).
- `user`: `username` (unique; stored stripped + lowercase, so uniqueness is case-insensitive; 1-64 of `a-z 0-9 . _ -`), `password_hash`, `role` (`admin` | `viewer`, validated in
  `core/auth.py::ROLES`), `is_active`, `created_at`, `last_login_at`, `failed_logins`, `locked_until`. Timestamps are naive UTC.
- Passwords: `core/passwords.py`, stdlib `hashlib.scrypt` (N=2^15, r=8, p=1, 16-byte random salt, 32-byte key), the parameters inside the stored string
  (`scrypt$N$r$p$salt$key`) so they can be raised later (a login whose stored parameters are weaker re-hashes with the password in hand), `hmac.compare_digest`. Minimum 12
  characters, maximum 256. A hash or password is never logged, returned or put in an error message.
- **CLI** (`core/auth_cli.py`, run from `backend/`): `create-user <name> --role admin|viewer`, `set-password`, `disable`, `enable`, `list`, `revoke-sessions [name]`. Passwords come from a
  terminal prompt (twice) or one line on stdin, never argv. `list` never prints a hash. Setup steps: `backend/OPS_RUNBOOK.md`, "Login accounts".
- Foreign keys are off in this database, so **disable, set-password and revoke-sessions delete the user's `usersession` rows explicitly**. `set-password` also clears `failed_logins` / `locked_until`.

## Sessions and the cookie

- `POST /api/auth/login` `{username, password}` -> 200 `{username, role}` and a `Set-Cookie`; `POST /api/auth/logout` -> 204 (needs a session); `GET /api/auth/me` -> `{username, role}` (401 without a session).
- The cookie `fathom_session` holds an opaque `secrets.token_urlsafe(32)` (256 bits); **only its SHA-256 is stored** (`usersession.token_hash`, the primary key), with `user_id`, `created_at`,
  `expires_at`, `last_seen_at`, `ip`, `user_agent`. Flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` = the absolute lifetime, **`Secure` only when `SESSION_COOKIE_SECURE=true`**
  (default off: the app is reached over plain `http://localhost`, and Safari discards `Secure` cookies there; turn it on only behind TLS).
- **Defaults:** idle timeout 7 days (`SESSION_IDLE_DAYS`), absolute lifetime 30 days (`SESSION_ABSOLUTE_DAYS`). The token **rotates on every login** (a session cookie sent with the login request is deleted),
  logout deletes the row and clears the cookie, expired rows are dropped when found and swept at the next login. `last_seen_at` is refreshed **at most once every 300 s and read first**
  (`SESSION_TOUCH_SECONDS`, the pattern of `record_ticker_view`), so the idle timeout is accurate to five minutes and a page of requests is not a page of writes.
- A session is also refused when its user is disabled or gone.

## Login throttling (all temporary)

Per user, in the DB (`failed_logins`, `locked_until`, survives a restart): `LOGIN_MAX_FAILURES` (5) wrong passwords lock the user for `LOGIN_LOCKOUT_MINUTES` (15); while locked even the right password is
refused (429); a success resets both. The same counter is kept **in memory for names that do not exist**, so a lockout cannot be used to find out which accounts exist. Per source address:
`LOGIN_SOURCE_MAX_FAILURES` (30) failures in `LOGIN_SOURCE_WINDOW_MINUTES` (15) block that source until the oldest ages out. Behind the SSH tunnel every request comes from 127.0.0.1, so the per-source
limit is in effect one global limit (an attacker with tunnel access can therefore delay a legitimate login by up to the window, never lock anyone out for good; `set-password` clears a user lock at once).
Answers: wrong password / unknown user / inactive user are all **401 `{"detail": "Invalid credentials"}`**; a throttled attempt is **429 `Too many failed sign-in attempts. Try again later.`** with `Retry-After`.
An unknown, inactive or locked account pays for one dummy scrypt check, so timing does not name an account.

## Enforcement

- `core/main.py` builds the app with the one default dependency `core.auth.authorize`; the Host / Origin / `X-Fathom-Request` guard (`core/request_guard.py`) is middleware and runs first
  (400 / 403 before any 401). FastAPI parses a JSON body before dependencies run, so a request with malformed JSON can still get 422 before 401; no data is involved.
- **`core/route_roles.py` is the one registry**: every route is `public`, `viewer` (any signed-in user) or `admin` (403 for a viewer). A route missing from it is treated as admin-only, and
  `tests/test_route_roles_registry.py` fails if a route is missing, an entry is stale, a write method is `viewer` without being in `VIEWER_ALLOWED_WRITES`, any route lacks the dependency,
  or a `{ticker}` route lacks the ticker guard. Public: `GET /api/health` (GET only; `bin/start.sh` polls it) and `POST /api/auth/login`. Viewer-allowed writes: `POST /api/auth/logout` and
  `POST /api/tickers/{ticker}/step3/manual` (a pure calculation, no I/O). **Adding a route means adding one line there.**
- The full role table is generated from the registry; the admin-only reads are `GET /api/config/cron-health`, `/api/config/data-source-health`, `/api/config/data-groups` (plan, `key_problem_detail`) and
  `GET /api/tickers/{ticker}/financials/cash-flow-cell-check` (an on-demand SEC EDGAR + FMP call).
- **Audit** (`core/audit.py`, table `auditlog`): one row per non-GET request outcome (`event = "request"`, written after the response is decided, in a worker thread, guard refusals included) and
  per login event (`login_ok`, `login_fail`, `login_blocked`, `lockout`, `logout`). Columns: `ts`, `user_id`, `username`, `method`, `path` (no query string), `status`, `ip`, `event`. **No body, password, token, hash or header.**
  A failed login row carries a username only when the account exists (an unknown name may be a password typed in the wrong box). A failed audit write is logged and swallowed. The table is not pruned.

## Viewer rules (server-side)

A *viewer* is anyone signed in who is not an admin (the code is fail-closed: `core.auth.is_restricted`).

- **Tracked tickers only.** `core/main.py::TickerPath` (on every `{ticker}` route) answers a generic **404 `{"detail": "Not found"}`** for any ticker that `classify_one` does not put in the stock or ETF
  universe, *before* the handler: no fetch, no cache write, no `TickerView` / `TickerScore` write. Admins are unaffected.
- **Cache only, write free.** For a viewer `summary`, `step1/2/3/4/5`, `financials`, `ratios`, `segmentation`, `analyst-ratings`, `institutional-ownership`, `speculative-growth`, `news`,
  `etf-overview` and `trend-analysis` run with `cache_only=True` (new parameters on `get_news_data` and `get_etf_overview`); `summary` skips `touch_existing_ticker_view` / `record_ticker_view`;
  `etf-overview` does no daily-bar warm-up. `/score` serves the stored row, or re-derives a missing / blank / older-weights row from cached data with `persist=False`. Watchlist `rows` uses
  `read_only=True` (the consensus rating is cache-only and the computed `TickerScore` rows are not stored). Everything else a viewer can read was already stored-data-only.
  `tests/test_viewer_rules.py` pins it for every viewer `GET` route: zero calls reach the FMP client and zero non-SELECT statements reach the database (settings singletons pre-seeded: on a pristine
  database the first read of a settings page inserts its default row, an old idempotent behaviour the live database no longer shows).
- **Search.** `GET /api/tickers/search` for a viewer is `_search_tracked_universe(tracked_only=True)`: symbols of the stock and ETF universes only (the wide known set would list tickers a viewer gets a 404 for), no FMP call.
- **Chart.** No cache-only mode exists, so a viewer's `GET /chart` goes through `data/viewer_chart_cache.py`: an in-memory cache keyed by (ticker, range), TTL `VIEWER_CHART_CACHE_SECONDS` (default 60, 0 = off),
  concurrent misses for a key share one fetch, a failed load is not cached, at most 256 entries. An admin's chart is always live and does not fill it. The API token bucket (docs/specs/fmp-data-and-bar-cache.md) still applies to the fetch.
- **Redaction.** For a viewer: `GET /api/config/score-weights` returns `recompute.error = null` (state and counts stay); `GET /etf-overview` returns `reason = null`. `RecomputeRunOut`, `RecomputeSummary` and `UniverseAddOut`
  each have a `for_viewer()` that blanks the raw exception text; the two routes that return the latter two are admin-only, so that is defence in depth. The cron-health, data-source-health and data-groups reads are admin-only outright.

## Frontend (security step 4, 2026-10-13)

The backend contract above is unchanged; the frontend only consumes it. **The frontend hides; the backend refuses.** Nothing below is a security control, every admin write is still refused with 403 whatever the page shows, and
`proxy.ts` is only a convenience (it checks that a cookie exists, never that it is valid).

**Session state.** `lib/auth/AuthProvider.tsx` (mounted in `app/layout.tsx`) calls `GET /api/auth/me` once and exposes `useAuth()`: `user`, `role`, `isAdmin`, `isLoading`, `login()`, `logout()`. `isAdmin` is false until `/auth/me` has answered, so a viewer never sees an admin
control flash. Login and logout clear the whole SWR cache (`lib/auth/session.ts::clearClientCache`) so one user's data cannot show for the next; logout then loads `/login` with a full page load (`lib/auth/navigate.ts`), which also drops all in-memory state.
`lib/auth/testAuth.tsx` (`<TestAuth role=...>`) and `lib/auth/adminAuthMock.ts` (`vi.mock` of the provider as a signed-in admin, `setMockRole("viewer")` to flip) are the test seams.

**`/login`** (`components/auth/LoginForm.tsx`): username and password, autofocus, `autocomplete="username"` / `"current-password"`, submit disabled while pending or while a field is empty. A 401 reads "Invalid username or password." (never the backend's wording); a 429 reads "Too many failed sign-in attempts." plus a
wait hint from `Retry-After` ("about N minutes"); any other failure is a neutral "Couldn't sign in". After sign-in, and for a visitor who is already signed in, it loads the `next` parameter or `/screener`. **`next` is accepted only as a same-origin relative path**
(`lib/auth/safeNext.ts::safeNextPath`): it must start with a single `/`, with no backslash, no control character (a browser drops a tab or newline inside a URL), no scheme, not `//`, not `/login`, and a parse against a throwaway origin must stay on it. The bar on this page is just the name.

**API client** (`lib/api/client.ts`). Failures throw `ApiError` (`status`, `detail`, `retryAfter`; the message is still `METHOD path failed: STATUS - detail`, so existing `.includes("409")` checks and `errorDetail` work). A **401** on anything but `/auth/login` and `/auth/logout`
clears the SWR cache and loads `/login?next=<page>` once (module flag, however many requests fail together), **never from `/login` itself** (no loop), and **settles nothing**, so no caller shows an error or toast for a page that is about to be replaced. A **403 "Admin access required"**
becomes the detail "Admin access required — this account is view-only." through the usual `errorDetail` path. `X-Fathom-Request` and the no-raw-`fetch` rule are unchanged; `/api/health` is untouched.

**Route gating** (`proxy.ts`, Next 16's `middleware`): a request without a `fathom_session` cookie is redirected to `/login?next=<path>` with a **relative** `Location` (the browser resolves it against the address it used, so the SSH-tunnel host is never rewritten). Not applied to `/login`, `/api`, `/_next` and static files. The gate cannot tell a real
cookie from a made-up one, and an expired cookie gets through to the page, where `/auth/me` answers 401 and the client redirects. `/styleguide` is admin-only (`app/styleguide/page.tsx` gates `StyleguideContent`; a non-admin is sent to `/`).

**Chrome.** The top bar shows the username, the role and **Sign out**; a signed-out visitor, and the login page, see only the name. Nothing else in the nav is hidden for a viewer (every page is readable).

**What a viewer does not get** (`components/auth/AdminOnly.tsx` or `useAuth().isAdmin`; render nothing, not a disabled button, except the Settings values, which are shown disabled because they teach "read-only"):

| Where | Hidden for a viewer | File |
|---|---|---|
| Settings, the six readable sections (Discount rate, Score weighting, Economic moat, REIT, Liquidity, Weinstein) | Save, Reset to defaults, the recompute confirmation; the fields stay, disabled in one `<fieldset>`, with a "View only" note | `components/settings/SettingsLayout.tsx` (`SettingsSection`, `SettingsFooter`) |
| Settings > Scheduled jobs, FMP data groups | the sections are not listed or mounted (their reads are admin-only) | `app/settings/page.tsx` |
| Ticker header | universe Add / Remove, Add to watchlist, Refresh; the ETF header's universe and ETF watchlist button | `components/ticker/TickerHeader.tsx`, `EtfHeader.tsx` |
| Moat tab | the rating picker (the rating shows as text) | `components/ticker/EconomicMoatTab.tsx` |
| Valuation tab, Custom valuation | Save, Activate, Revert to auto, Delete (the calculator still runs: `step3/manual` is allowed for a viewer) | `components/step3/ManualCalculationPanel.tsx` |
| Debt tab (banks) | the CET1 / NPL form | `components/step5/Step5Card.tsx` |
| Financials tab | the SEC cell-check magnifier (an admin-only SEC EDGAR + FMP call) | `components/ticker/FinancialsStatementTable.tsx` |
| Stocks screener | Recompute all scores, Add to watchlist, Save current view, Delete view (applying a saved view and Reset stay) | `app/screener/page.tsx`, `components/screener/SavedFiltersBar.tsx` |
| ETFs screener | Add to watchlist, Save / Delete view | `app/etfs/page.tsx`, the same bar |
| Opportunities | Add to watchlist (Export stays) | `app/opportunities/page.tsx` |
| Watchlist page | rename pencil, delete, per-row remove (Export stays) | `components/watchlist/WatchlistNameEditor.tsx`, `app/watchlist/page.tsx`, `components/watchlist/tableParts.tsx` |

**Admin-only reads are never made for a viewer** (they would 403). The ticker page's "not refreshing" badge (`components/shared/GroupOffBadge.tsx`) used to fetch `/config/data-groups` on every tab; it now passes `useDataGroups(isAdmin)` and a viewer neither sees the badge nor makes the request.
The two Settings sections that read cron-health / data-groups are not mounted for a viewer. `useDataSourceHealth` has no caller. `lib/api/adminGuard.test.ts` keeps a new component from calling a write or an admin-only read without a guard (below).

**Restricted data.** A 404 on the ticker summary (`errorStatus(error) === 404`) is the "not found" page for an admin and, for a viewer, `TickerNotFound`'s "isn't available" state ("This ticker isn't tracked"), not an error line or a spinner. The search box says "No tracked ticker matches ..." for a viewer. A redacted field arrives as `null`:
the ETF overview with `reason: null` reads "Fund details for X are not available right now."; the score-recompute failure line drops the quoted reason and no longer says "unknown error".

**Tests.** `lib/auth/AuthProvider.test.tsx`, `components/auth/LoginForm.test.tsx`, `lib/auth/safeNext.test.ts`, `lib/api/clientAuth.test.ts`, `proxy.test.ts`, `components/auth/AdminOnly.test.tsx`, `components/auth/viewerControls.test.tsx` (one sample of each control group, as admin and viewer),
`app/settings/page.roles.test.tsx` (the real sections with a recording transport: no admin-only read for a viewer), `components/ticker/viewerStates.test.tsx`, plus viewer cases in the page tests. **`lib/api/adminGuard.test.ts`** is a static check: a source file that calls `apiPost` / `apiPut` / `apiPatch` / `apiDelete`, an admin-only read, or a function that does must
contain `AdminOnly`, `isAdmin` or `SettingsFooter`, or be imported only by files that do, up to a page. It is file-level, not a proof (it cannot see whether the guard wraps the right element), and `components/etf-screener/SavedEtfFiltersBar.tsx` is its one allowlisted file (its guard lives in `SavedFiltersBarView`).

**Not verified without a browser:** the visual result, the redirects through a real browser and the SSH tunnel, cookie behaviour across the tunnel, and how each tab looks with cache-only data. See the step 4 report in docs/decisions.md for the click-through list.

## Not changed

Cron jobs, `pipeline/`, `scripts/` and the Moat-check pipeline read and write the database and call FMP directly and never go through the HTTP API (nothing outside `core/main.py` imports it; the only HTTP the repo's scripts make to the app
is `bin/start.sh`'s `GET /api/health`), so none of them needs a login. Scoring, `SCORE_FORMULA_VERSION`, the watchlist cap, the tracked-universe rule and every schema other than the three new tables are unchanged.
