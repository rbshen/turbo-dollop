from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .parent.parent, not .parent -- this file now lives at backend/core/config.py,
# one directory deeper than when BASE_DIR was first written relative to
# backend/ itself. Both consumers below are load-bearing: env_file is how
# the real FMP API key gets read from backend/.env, and db.py's DB_PATH is
# built from this same BASE_DIR -- a stray .parent here would silently
# point the running app at a fresh, empty backend/core/fathom.db instead
# of the real ~800MB backend/fathom.db, with no error at startup.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    # Global kill switch for pausing the FMP subscription -- when False, the
    # app must run entirely cache-only, no live network attempts. Enforced
    # at two layers: clients.fmp_client.FMPClient.get (the literal choke
    # point every FMP call passes through, guaranteeing zero network
    # attempts) and core.cache's get_or_fetch/get_or_fetch_earnings_aware/
    # force_fetch (which additionally preserve stale-cache-serving
    # semantics, rather than just failing like a genuine fetch error would).
    # Read once at process start -- toggling the FMP_ENABLED env var
    # requires a backend restart to take effect, same as every other
    # Settings field.
    fmp_enabled: bool = True
    # Gates only GET /api/config/cron-health's reporting and the frontend
    # banner -- CronRunLog rows keep being written regardless (see
    # core/cron_health.py::cron_heartbeat), so history isn't lost and
    # nothing needs to be gated at the write layer. Useful for muting
    # cron-health surfacing during an extended FMP_ENABLED=false pause,
    # where the operator already knows the situation and doesn't need a
    # second banner competing with FmpPausedBanner. Read once at process
    # start, same as every other Settings field.
    cron_health_enabled: bool = True
    database_path: str = "fathom.db"
    cache_staleness_days: int = 7
    # Distinct from cache_staleness_days -- Yahoo Finance OHLCV bars
    # (YahooPriceCache) are trading-day-grain data that gets a new bar every
    # day the nightly trend job runs, unlike fundamentals which only change
    # quarterly, so a much tighter staleness window applies here. See
    # clients/yahoo_cache.py.
    yahoo_price_cache_staleness_days: int = 1
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
    # News is far more time-sensitive than fundamentals -- a short TTL
    # (minutes, not days) so repeat tab views within a session don't each
    # hit FMP, without pretending news is as static as financials. See
    # news_data.py.
    news_cache_ttl_minutes: int = 20
    # SEC EDGAR's fair-use policy requires a descriptive User-Agent
    # identifying the requester with real contact info (a bare/generic UA
    # gets 403'd) -- override via SEC_EDGAR_USER_AGENT in .env with a real
    # app name and contact email before relying on this in production.
    sec_edgar_user_agent: str = "Fathom Fundamentals Screener (set SEC_EDGAR_USER_AGENT in .env)"


settings = Settings()
