"""Single normalization choke point for ticker strings entering Fathom from
any source (Wikipedia scrape, typeahead search, watchlist add, direct URL
navigation, cron/pipeline scripts). Canonical form is hyphen-notation
(`BRK-B`), matching FMP's own native symbol and what typeahead search
already returns -- see CLAUDE.md's "Ticker dot/hyphen normalization"
section for the investigation this codifies.

TICKER_ALIASES is deliberately a narrow, confirmed allowlist, not a blanket
dot-to-hyphen replace: typeahead search (data/ticker_search.py) queries
FMP's entire live ticker universe, not just Fathom's tracked S&P 500/Dow
set, so a foreign-exchange ticker using a dot for something other than a
dual-class share suffix (e.g. an FMP-style exchange suffix) must pass
through unchanged rather than being silently mangled. These two are the
only confirmed dot-notation tickers in Fathom's tracked universe (verified
directly against IndexConstituent -- see investigation notes)."""

TICKER_ALIASES = {"BRK.B": "BRK-B", "BF.B": "BF-B"}

def normalize_ticker(ticker: str) -> str:
    cleaned = ticker.strip().upper()
    return TICKER_ALIASES.get(cleaned, cleaned)


def is_non_us_ticker(ticker: str) -> bool:
    """True for a dotted foreign-primary-listing symbol (e.g. 0700.HK, MC.PA) -- the
    two dot-notation US class shares are already normalized to their hyphen form by
    normalize_ticker before this is ever called, so this can't misfire on them. Only
    used as is_us_listed's no-profile fallback; a US OTC ticker (CNSWF, EVVTY, SINGY)
    has no dot and reads as US."""
    return "." in ticker


# FMP /profile `exchange` values that count as a US listing for the daily-price
# migration (P2). US = listed/traded on a US venue, NOT company domicile: an
# NYSE-listed Irish ADR is US, an HKSE listing of a British bank is not. FMP
# reports NYSE Arca ETFs (SPY, TECL) as "AMEX"; OTC is treated as US by
# decision (CNSWF/EVVTY/SINGY route to FMP).
US_EXCHANGES = frozenset(
    {"NYSE", "NASDAQ", "AMEX", "NYSE ARCA", "NYSEARCA", "ARCA", "NYSE AMERICAN", "CBOE", "BATS", "OTC"}
)


def is_us_listed(ticker: str, exchange: str | None = None) -> bool:
    """True when `ticker` should route to the US daily-price path. With a
    known listing `exchange` (the cached FMP profile's field) it decides
    alone; with none -- sector ETFs and indices like ^GSPC have no cached
    profile -- a symbol with no dot suffix is US (same rule as the previous
    dot-only routing, which this is a strict refinement of)."""
    if exchange:
        return exchange.strip().upper() in US_EXCHANGES
    return not is_non_us_ticker(ticker)
