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

import re

TICKER_ALIASES = {"BRK.B": "BRK-B", "BF.B": "BF-B"}

# The one ticker-shape check for every boundary that takes a symbol from outside (API path/body/query fields).
# ASCII letters and digits, "." and "-" after the first character (BRK-B, 0700.HK, MC.PA), an optional single
# leading "^" for an index (^GSPC), 1-12 characters in all. A leading "-" or "." is never valid, so no ticker can
# start with a CSV formula character (=, +, -, @). Applied to the normalized form (is_valid_ticker), so the
# case and the BRK.B/BF.B aliases behave exactly as normalize_ticker already makes them; it never rewrites a ticker.
MAX_TICKER_LENGTH = 12
TICKER_PATTERN = re.compile(r"\^?[A-Z0-9][A-Z0-9.\-]*")
INVALID_TICKER_MESSAGE = "Invalid ticker symbol"


class InvalidTickerError(ValueError):
    """A string that is not a ticker symbol. The message is generic on purpose (the input is not echoed)."""

    def __init__(self) -> None:
        super().__init__(INVALID_TICKER_MESSAGE)

def normalize_ticker(ticker: str) -> str:
    cleaned = ticker.strip().upper()
    return TICKER_ALIASES.get(cleaned, cleaned)


def is_valid_ticker(raw: object) -> bool:
    """True when `raw` is a string that normalizes to a ticker-shaped symbol (see TICKER_PATTERN). Non-ASCII input is
    refused before upper() can fold it into ASCII (dotless i -> I)."""
    if not isinstance(raw, str) or not raw.isascii():
        return False
    if raw.strip(" ") != raw.strip():  # only plain spaces may pad it, never a tab, CR or LF
        return False
    cleaned = normalize_ticker(raw)
    return len(cleaned) <= MAX_TICKER_LENGTH and TICKER_PATTERN.fullmatch(cleaned) is not None


def require_valid_ticker(raw: object) -> str:
    """`raw` unchanged when it is a valid ticker, else InvalidTickerError. Callers keep their own normalize_ticker call."""
    if not is_valid_ticker(raw):
        raise InvalidTickerError()
    return raw  # type: ignore[return-value]  # is_valid_ticker checked it is a str


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
