from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    database_path: str = "fathom.db"
    cache_staleness_days: int = 7
    # Step 3's CAPM discount rate input (see step6_intrinsic_value_calculation_
    # prompt.md §5) -- deliberately NOT auto-fetched. The source
    # (market-risk-premia.com/us.html) is technically scrapeable but
    # undocumented/unstable and its terms only support citing the number, not
    # automated re-fetching by a third party. A human updates this
    # periodically, same treatment as Step 2's growth-catalyst notes.
    # Expressed as a decimal fraction (e.g. 0.05 for 5%), 5-year trailing
    # average per the spec. Update via MARKET_RISK_PREMIUM_US in .env.
    market_risk_premium_us: float = 0.05
    # SEC EDGAR's fair-use policy requires a descriptive User-Agent
    # identifying the requester with real contact info (a bare/generic UA
    # gets 403'd) -- override via SEC_EDGAR_USER_AGENT in .env with a real
    # app name and contact email before relying on this in production.
    sec_edgar_user_agent: str = "Fathom Fundamentals Screener (set SEC_EDGAR_USER_AGENT in .env)"


settings = Settings()
