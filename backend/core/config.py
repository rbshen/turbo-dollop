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
    # Massive.com (a Polygon.io rebrand) -- the daily-bar price-data
    # provider replacing Yahoo Finance for every US-listed daily-bar
    # consumer (see docs/massive_feasibility_investigation_2026-09-23.md).
    # Same read-once-at-process-start / global-kill-switch convention as
    # fmp_enabled: False routes every ticker straight to Yahoo
    # (clients/daily_bar_sources.py::YahooDailySource), zero Massive calls,
    # the full rollback lever with no code revert needed. Unlike
    # fmp_enabled, Yahoo stays wired in regardless (non-US tickers always
    # need it, see core/tickers.py::is_non_us_ticker), so there is no
    # equivalent of FMP_ENABLED=false's "serve stale cache, no live calls"
    # degrade mode here -- disabling Massive just means "use Yahoo for
    # everything," a live source either way.
    massive_enabled: bool = True
    massive_api_key: str = ""
    massive_base_url: str = "https://api.polygon.io"
    # Gates only GET /api/config/cron-health's reporting and the frontend
    # banner -- CronRunLog rows keep being written regardless (see
    # core/cron_health.py::cron_heartbeat), so history isn't lost and
    # nothing needs to be gated at the write layer. Useful for muting
    # cron-health surfacing during an extended FMP_ENABLED=false pause,
    # where the operator already knows the situation and doesn't need a
    # second banner competing with FmpPausedBanner. Read once at process
    # start, same as every other Settings field.
    cron_health_enabled: bool = True
    # Insider Activity is shelved (2026-09-20): the tab is off the ticker
    # page and the feature makes no FMP calls and touches no cache while
    # this is False. The code (data/insider_activity_data.py, the route, and
    # the frontend components) is deliberately left in place so it can be
    # revived by setting INSIDER_ACTIVITY_ENABLED=true and re-adding the tab
    # (frontend/lib/tickerTabs.ts + TickerTabsContainer.tsx). Gated in
    # get_insider_activity_data itself, so the route inherits it -- same
    # shape as cron_health_enabled/get_cron_health(). Read once at process
    # start, same as every other Settings field.
    insider_activity_enabled: bool = False
    database_path: str = "fathom.db"
    cache_staleness_days: int = 7
    # YahooPriceCache (the FMP-paused Price/Quote fallback) is judged by
    # market session, not a flat window -- see clients/yahoo_cache.py::
    # _is_stale. This is the one tunable: how long a fetch taken while the
    # session is OPEN stays fresh (after the close, a fetch is fresh until
    # the next session's close; no setting involved).
    yahoo_quote_intraday_ttl_seconds: int = 60
    # daily_bar_staleness_days (FMP daily EOD price bars' own staleness
    # window) was removed 2026-09-18: Chart tab and Liquidity Zone
    # detection, its only two consumers, both dropped FMP as a data source
    # entirely (Chart moved to zero-cache on-demand Yahoo the day before;
    # Liquidity Zones followed the same day, moving to Yahoo bars) --
    # see CLAUDE.md's Liquidity Zone section for the staleness bug this
    # setting existed to fix, now moot since the FMP-backed cache it gated
    # (clients/daily_price_sources.py::FMPDailyBarSource) no longer exists.
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
