from core.tickers import normalize_ticker


def test_normalizes_known_dual_class_share_aliases():
    assert normalize_ticker("BRK.B") == "BRK-B"
    assert normalize_ticker("BF.B") == "BF-B"


def test_is_case_insensitive():
    assert normalize_ticker("brk.b") == "BRK-B"
    assert normalize_ticker("aapl") == "AAPL"


def test_strips_whitespace():
    assert normalize_ticker("  AAPL  ") == "AAPL"
    assert normalize_ticker(" BRK.B ") == "BRK-B"


def test_already_hyphenated_alias_passes_through_unchanged():
    assert normalize_ticker("BRK-B") == "BRK-B"


def test_unaliased_ticker_passes_through_unchanged():
    assert normalize_ticker("AAPL") == "AAPL"
    assert normalize_ticker("MSFT") == "MSFT"


def test_unlisted_dotted_string_is_not_mangled():
    # Narrow-allowlist design decision: typeahead search queries FMP's
    # entire live ticker universe (see ticker_search.py), which could
    # surface a foreign-exchange symbol using a dot for something other
    # than a dual-class share suffix. Only the two confirmed pairs in
    # TICKER_ALIASES are remapped -- everything else must pass through
    # unchanged, not get a blanket dot-to-hyphen replace.
    assert normalize_ticker("VOD.L") == "VOD.L"
