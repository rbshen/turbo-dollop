from core.tickers import from_massive_symbol, is_non_us_ticker, normalize_ticker, to_massive_symbol


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


def test_to_massive_symbol_converts_known_class_shares_to_dot_notation():
    assert to_massive_symbol("BRK-B") == "BRK.B"
    assert to_massive_symbol("BF-B") == "BF.B"


def test_to_massive_symbol_passes_through_unaliased_tickers_unchanged():
    assert to_massive_symbol("AAPL") == "AAPL"
    assert to_massive_symbol("0700.HK") == "0700.HK"


def test_from_massive_symbol_is_the_inverse_of_to_massive_symbol():
    assert from_massive_symbol("BRK.B") == "BRK-B"
    assert from_massive_symbol("BF.B") == "BF-B"
    assert from_massive_symbol("AAPL") == "AAPL"


def test_is_non_us_ticker_flags_dotted_foreign_listings():
    assert is_non_us_ticker("0700.HK") is True
    assert is_non_us_ticker("MC.PA") is True
    assert is_non_us_ticker("VOD.L") is True


def test_is_non_us_ticker_does_not_flag_normalized_class_shares_or_plain_tickers():
    # BRK.B/BF.B are already normalize_ticker'd to their hyphen form before
    # this is ever called, so a normalized class share must never read as
    # non-US just because the raw input happened to contain a dot.
    assert is_non_us_ticker(normalize_ticker("BRK.B")) is False
    assert is_non_us_ticker("AAPL") is False
    assert is_non_us_ticker("CNSWF") is False  # OTC, no dot -- caught by the empty-result fallback instead
