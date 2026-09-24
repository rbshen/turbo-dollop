import core.tickers as tickers_module
from core.tickers import from_massive_symbol, is_non_us_ticker, normalize_ticker, resolve_daily_bar_source_label, to_massive_symbol


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


def test_resolve_daily_bar_source_label_is_fmp_for_us_tickers_while_daily_prices_is_live():
    assert resolve_daily_bar_source_label("AAPL") == "fmp"


def test_resolve_daily_bar_source_label_prefers_massive_for_us_tickers_when_daily_prices_off(monkeypatch):
    import core.data_groups as dg

    dg.set_group_enabled("daily_prices", False)
    monkeypatch.setattr(tickers_module.settings, "massive_enabled", True)
    assert resolve_daily_bar_source_label("AAPL") == "massive"


def test_resolve_daily_bar_source_label_for_non_us_tickers_follows_daily_prices_intl():
    import core.data_groups as dg

    assert resolve_daily_bar_source_label("0700.HK") == "fmp"
    dg.set_group_enabled("daily_prices_intl", False)
    assert resolve_daily_bar_source_label("0700.HK") == "yahoo"
    assert resolve_daily_bar_source_label("AAPL") == "fmp"  # the US group is independent


def test_resolve_daily_bar_source_label_is_yahoo_when_daily_prices_off_and_massive_disabled(monkeypatch):
    import core.data_groups as dg

    dg.set_group_enabled("daily_prices", False)
    monkeypatch.setattr(tickers_module.settings, "massive_enabled", False)
    assert resolve_daily_bar_source_label("AAPL") == "yahoo"


def test_is_us_listed_uses_exchange_not_domicile_and_falls_back_to_the_dot_rule():
    from core.tickers import is_us_listed

    for exchange in ("NYSE", "NASDAQ", "AMEX", "CBOE", "OTC", "nasdaq"):
        assert is_us_listed("X", exchange) is True  # ADRs / foreign-domiciled US listings are US
    assert is_us_listed("0005.HK", "HKSE") is False
    assert is_us_listed("XLK", None) is True and is_us_listed("^GSPC", None) is True  # no profile, no dot
    assert is_us_listed("0700.HK", None) is False
