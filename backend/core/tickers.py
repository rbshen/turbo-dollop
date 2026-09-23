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

from core.config import settings

TICKER_ALIASES = {"BRK.B": "BRK-B", "BF.B": "BF-B"}

# Reverse of TICKER_ALIASES -- Massive/Polygon uses dot notation for class
# shares (confirmed live, see docs/massive_feasibility_investigation_2026-09-23.md
# §2a: "BRK.B (dot) works; BRK-B ... returns 200 with resultsCount: 0"), the
# opposite of Fathom's own hyphen canonical form. Deliberately the same
# narrow two-entry allowlist as TICKER_ALIASES, not a blanket hyphen->dot
# replace -- a genuinely non-US/OTC ticker could contain a hyphen for an
# unrelated reason and must never be mangled into a bogus Massive symbol.
MASSIVE_TICKER_ALIASES = {v: k for k, v in TICKER_ALIASES.items()}  # {"BRK-B": "BRK.B", "BF-B": "BF.B"}


def normalize_ticker(ticker: str) -> str:
    cleaned = ticker.strip().upper()
    return TICKER_ALIASES.get(cleaned, cleaned)


def to_massive_symbol(ticker: str) -> str:
    """Fathom canonical (hyphen) -> Massive/Polygon's own symbol (dot) for
    the two known class shares; every other ticker passes through
    unchanged. Call with an already-normalize_ticker'd symbol."""
    return MASSIVE_TICKER_ALIASES.get(ticker, ticker)


def from_massive_symbol(symbol: str) -> str:
    """Inverse of to_massive_symbol -- used when reading a ticker column
    back out of a Massive response (e.g. grouped-daily, which is indexed by
    Massive's own dot-notation symbol)."""
    return TICKER_ALIASES.get(symbol, symbol)


def is_non_us_ticker(ticker: str) -> bool:
    """True for a ticker Massive/Polygon (US-market-only, confirmed in the
    feasibility investigation §2j) can never serve -- routed straight to
    Yahoo. A normalized ticker containing '.' is a foreign-primary-listing
    suffix (e.g. 0700.HK, MC.PA) -- the two dot-notation US class shares are
    already normalized to their hyphen form by normalize_ticker before this
    is ever called, so this can't misfire on them. This is a necessary but
    not sufficient check -- a US OTC ticker (CNSWF, EVVTY, SINGY) has no dot
    and still needs the caller's own per-ticker empty-result fallback (see
    clients/daily_bar_sources.py) to end up on Yahoo."""
    return "." in ticker


def resolve_daily_bar_source_label(ticker: str) -> str:
    """Best-effort label for which provider generally serves this ticker's
    daily bars -- "yahoo" for a non-US ticker or when Massive is disabled,
    "massive" otherwise. Informational only (e.g.
    LiquidityZoneAnalysis.source), NOT a literal per-fetch record of which
    provider actually answered a specific call: a per-ticker Massive->Yahoo
    fallback (see clients/daily_bar_sources.py::MassiveWithYahooFallback)
    could silently make this label wrong for one specific night without
    anything here knowing, the same tolerance every other informational-
    only field in this codebase already accepts."""
    return "yahoo" if is_non_us_ticker(ticker) or not settings.massive_enabled else "massive"
