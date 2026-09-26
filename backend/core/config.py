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
    # Distinct from cache_staleness_days above: insider trading (Form 4)
    # filings are event-driven -- an insider can file any business day, and
    # a filing is due within 2 business days of the trade -- not tied to
    # the ticker's earnings cycle the way statement-grain data is, so the
    # shared 7-day window would leave a fresh filing invisible for up to a
    # week. See data/insider_activity_data.py.
    insider_staleness_days: int = 1
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
