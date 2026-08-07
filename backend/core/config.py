from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .parent.parent, not .parent -- this file now lives at backend/core/config.py,
# one directory deeper than when BASE_DIR was first written relative to
# backend/ itself. Both consumers below are load-bearing: env_file is how
# the real FMP/Alpha Vantage keys get read from backend/.env, and db.py's
# DB_PATH is built from this same BASE_DIR -- a stray .parent here would
# silently point the running app at a fresh, empty backend/core/fathom.db
# instead of the real ~800MB backend/fathom.db, with no error at startup.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    database_path: str = "fathom.db"
    cache_staleness_days: int = 7
    # Distinct from cache_staleness_days above: staleness controls when a
    # cached row is refetched from FMP, not when it's deleted. This bounds
    # FundamentalsCache's actual row count, which only grows from tickers
    # looked up once outside the nightly-refreshed S&P 500/Dow universe (a
    # ticker inside that universe is upserted in place forever, never
    # accumulating rows) -- see pipeline/prune_cache.py.
    cache_retention_days: int = 180
    # Deliberately much tighter than cache_staleness_days -- fundamentals
    # (revenue, balance sheet) only change a few times a year, but a forex
    # spot rate moves daily. 1 day balances "not a week-stale rate" against
    # "not refetching on every request" -- see the non-USD currency
    # conversion investigation in CLAUDE.md-adjacent notes / step3_data.py.
    fx_rate_staleness_days: int = 1
    # News is far more time-sensitive than fundamentals -- a short TTL
    # (minutes, not days) so repeat tab views within a session don't each
    # hit FMP, without pretending news is as static as financials. See
    # news_data.py.
    news_cache_ttl_minutes: int = 20
    # Alpha Vantage NEWS_SENTIMENT -- free-tier key, 25 requests/day with a
    # ~1 req/sec burst throttle (confirmed live 2026-08-04), far tighter
    # than FMP's. 12hr (not FMP news's 20min) keeps real ticker-page-view
    # traffic affordable against that cap -- see news_sentiment_data.py.
    alpha_vantage_api_key: str = ""
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    news_sentiment_cache_ttl_minutes: int = 720
    # SEC EDGAR's fair-use policy requires a descriptive User-Agent
    # identifying the requester with real contact info (a bare/generic UA
    # gets 403'd) -- override via SEC_EDGAR_USER_AGENT in .env with a real
    # app name and contact email before relying on this in production.
    sec_edgar_user_agent: str = "Fathom Fundamentals Screener (set SEC_EDGAR_USER_AGENT in .env)"


settings = Settings()
