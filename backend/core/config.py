from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .parent.parent, not .parent -- this file now lives at backend/core/config.py,
# one directory deeper than when BASE_DIR was first written relative to
# backend/ itself. Both consumers below are load-bearing: env_file is how
# the real FMP API key gets read from backend/.env, and db.py's DB_PATH is
# built from this same BASE_DIR -- a stray .parent here would silently
# point the running app at a fresh, empty backend/core/fathom.db instead
# of the real backend/fathom.db (~1.2GB as of 2026-09), with no error at startup.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    # Outbound FMP protection (clients/fmp_client.py). The API process paces its own requests with a token bucket
    # (FMP_API_RATE_PER_MINUTE sustained, FMP_API_BURST at once; 0 = off); the plan limit is 300/min (Starter). Cron
    # jobs run in their own processes and never enable it (they keep their own min_request_interval pacing).
    fmp_api_rate_per_minute: int = 120
    fmp_api_burst: int = 40
    # A request that would have to wait longer than this for a token fails at once (a handled fetch failure) instead of queueing.
    fmp_api_max_wait_seconds: float = 15.0
    # Circuit breaker, every process: after this many 401/403 answers in a row stop sending for the cooldown (0 = off).
    fmp_auth_breaker_threshold: int = 5
    fmp_auth_breaker_cooldown_seconds: int = 300
    # FMP on/off is no longer an env flag: per-data-group toggles, the master
    # "disable all FMP" switch and the user's FMP plan live in the DB
    # (core/data_groups.py), editable in Settings and via
    # `python -m pipeline.data_groups`. Only the key/base URL stay here.
    # Gates only GET /api/config/cron-health's reporting and the frontend
    # banner -- CronRunLog rows keep being written regardless (see
    # core/cron_health.py::cron_heartbeat), so history isn't lost and
    # nothing needs to be gated at the write layer. Useful for muting
    # cron-health surfacing during an extended FMP pause,
    # where the operator already knows the situation and doesn't need a
    # second banner competing with FmpPausedBanner. Read once at process
    # start, same as every other Settings field.
    cron_health_enabled: bool = True
    database_path: str = "fathom.db"
    cache_staleness_days: int = 7
    # Company profile (name, sector, industry, description, exchange, beta)
    # is near-static reference data -- it doesn't change because of an
    # earnings report the way statement-grain data does (earnings-aware
    # gating would be the wrong model, not just a longer version of the
    # same one), and it essentially never changes week to week regardless.
    # A much longer flat window than cache_staleness_days both cuts real
    # waste and, as a side effect, stops profile rows fetched around the
    # same historical date from all coming due together every 7 days
    # (2026-08-16 cron thundering-herd follow-up -- see CLAUDE.md).
    profile_staleness_days: int = 30
    # Distinct from cache_staleness_days above: staleness controls when a
    # cached row is refetched from FMP, not when it's deleted. This bounds
    # FundamentalsCache's actual row count, which only grows from tickers
    # looked up once outside the nightly-refreshed S&P 500/Dow universe (a
    # ticker inside that universe is upserted in place forever, never
    # accumulating rows) -- see pipeline/prune_cache.py.
    cache_retention_days: int = 180
    # ETF /etf/info (fund facts, NAV, AUM, avg volume, sector weights). Fetched only when an ETF page's
    # Overview tab is opened (no nightly job), one small row per ETF. NAV/AUM/avg volume move daily,
    # the descriptive fields essentially never do, so a 1-day window keeps the numbers current without
    # a refetch on every view. A failed refetch serves the stale row (data/etf_data.py).
    etf_info_staleness_days: int = 1
    # FastAPI's /docs, /redoc and /openapi.json are off unless this is true (ENABLE_API_DOCS=true in the dev
    # shell or .env). Read once at import, because the routes are registered when the app is built.
    enable_api_docs: bool = False
    # Request guard (core/request_guard.py), comma-separated and re-read on every request. The app is reached at
    # http://localhost:3100 through an SSH tunnel; bin/common.sh derives the ports and origins from BACKEND_PORT /
    # FRONTEND_PORT, so set these only when the tunnel uses another local port or hostname.
    # Host header: hostnames and ports the backend answers to (the browser's :3100 and the Next proxy's :8002).
    allowed_hosts: str = "localhost,127.0.0.1,[::1]"
    allowed_host_ports: str = "8002,3100"
    # Origin (or Referer) a POST/PUT/PATCH/DELETE may come from.
    allowed_origins: str = "http://localhost:3100,http://127.0.0.1:3100"
    # Largest request body the API accepts, in bytes (core/body_limit.py): 413 above it, whether declared by Content-Length or streamed.
    # Re-read on every request; 0 turns the limit off. The largest legitimate body today is about 20 KB.
    max_request_body_bytes: int = 1_048_576

    # Login accounts and sessions (core/auth.py, docs/specs/auth.md). The session cookie is httpOnly + SameSite=Lax + Path=/.
    # SESSION_COOKIE_SECURE stays off by default: the app is reached over plain http://localhost:3100 and Safari drops Secure cookies
    # on http://localhost; turn it on only behind TLS. A session ends after session_idle_days without a request (refreshed at most
    # every 5 minutes) or session_absolute_days after login, whichever comes first.
    session_idle_days: float = 7
    session_absolute_days: float = 30
    session_cookie_secure: bool = False
    # Login throttle: login_max_failures wrong passwords for one user (or one unknown name) lock it for login_lockout_minutes;
    # login_source_max_failures failures from one source address inside login_source_window_minutes block that source until the
    # oldest one ages out. All temporary. Behind the SSH tunnel every request comes from 127.0.0.1.
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    login_source_max_failures: int = 30
    login_source_window_minutes: int = 15
    # Overall limit for one background score recompute (data/score_recompute.py): the worker stops itself at it, and a run older than this is
    # reaped (its worker terminated). The job normally takes about a minute. 0 = no limit.
    score_recompute_timeout_seconds: float = 3600
    # Audit-log retention (core/audit.py::prune_audit_log): rows older than this many days are deleted by the weekly `pipeline.prune_audit_log`
    # job and by `python -m core.auth_cli prune-audit` (--days overrides). Users and sessions are never touched.
    audit_retention_days: int = 180
    # Viewer GET /chart is served from an in-memory cache for this long, per (ticker, range), so viewers cannot multiply FMP calls.
    viewer_chart_cache_seconds: int = 60


settings = Settings()
