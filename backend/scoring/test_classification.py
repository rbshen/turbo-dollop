from scoring.classification import classify_company_type


def test_insurance_classified_before_bank_check_travelers():
    # TRV: sector "Financial Services", industry "Insurance - Property &
    # Casualty" -- shares a sector with Bank, so Insurance must be checked
    # first or this would fall through incorrectly.
    assert classify_company_type("Financial Services", "Insurance - Property & Casualty") == "Insurance"


def test_insurance_classified_before_bank_check_aig():
    assert classify_company_type("Financial Services", "Insurance - Diversified") == "Insurance"


def test_bank_still_classifies_correctly_within_financial_services():
    assert classify_company_type("Financial Services", "Banks - Diversified") == "Bank"


def test_utility_classified_by_sector():
    assert classify_company_type("Utilities", "Regulated Electric") == "Utility"


def test_reit_still_classifies_correctly():
    assert classify_company_type("Real Estate", "REIT - Retail") == "REIT/Property Developer"


def test_standard_fallback_unchanged():
    assert classify_company_type("Technology", "Consumer Electronics") == "Standard"


def test_capital_markets_broker_classified_as_bank_schwab():
    # SCHW: sector "Financial Services", industry "Financial - Capital
    # Markets" -- no "bank" substring, so this needs its own keyword.
    # Genuine banking subsidiary (Schwab Bank), netInterestIncome 42.5% of
    # revenue -- not on the non-lender override list.
    assert classify_company_type("Financial Services", "Financial - Capital Markets", "SCHW") == "Bank"


def test_investment_banking_still_classifies_as_bank_via_existing_substring():
    # IBKR: "Investment - Banking & Investment Services" already matches the
    # plain "bank" substring (via "banking") -- confirms no regression here
    # from the keyword-list change.
    assert classify_company_type("Financial Services", "Investment - Banking & Investment Services") == "Bank"


def test_asset_manager_with_ticker_omitted_defaults_to_bank():
    # No ticker supplied -- the non-lender override can't apply, so the
    # keyword match alone decides (matches pre-override behavior for any
    # caller that doesn't have a ticker handy).
    assert classify_company_type("Financial Services", "Asset Management") == "Bank"


def test_asset_manager_genuine_lender_stays_bank_ameriprise():
    # AMP (Ameriprise Bank, FSB): netInterestIncome 17.2% of revenue --
    # shares the identical "Asset Management" industry string with BLK
    # below, but is a genuine lender, so it's NOT on the override list.
    assert classify_company_type("Financial Services", "Asset Management", "AMP") == "Bank"


def test_asset_manager_non_lender_reverts_to_standard_blackrock():
    # BLK: netInterestIncome -0.09% of revenue (a small net expense, not
    # income) -- no banking subsidiary. Identical industry string to AMP
    # above, so ticker-level override is the only way to distinguish them.
    assert classify_company_type("Financial Services", "Asset Management", "BLK") == "Standard"


def test_asset_manager_non_lender_reverts_to_standard_examples():
    for ticker in ("APO", "ARES", "BEN", "BX", "IVZ", "KKR", "PFG", "TROW"):
        assert classify_company_type("Financial Services", "Asset Management", ticker) == "Standard"


def test_credit_services_genuine_lender_stays_bank_amex():
    # AXP: netInterestIncome 21.6% of revenue (real cardmember-loan book) --
    # shares the identical "Financial - Credit Services" industry string
    # with MA/V below, but is a genuine lender.
    assert classify_company_type("Financial Services", "Financial - Credit Services", "AXP") == "Bank"


def test_credit_services_genuine_lender_stays_bank_capital_one():
    # COF: netInterestIncome 61.9% of revenue -- Capital One is a chartered
    # national bank, not just a card issuer.
    assert classify_company_type("Financial Services", "Financial - Credit Services", "COF") == "Bank"


def test_credit_services_non_lender_reverts_to_standard_mastercard():
    # MA: netInterestIncome -2.2% of revenue (a small net expense) --
    # Mastercard is a payment network, not a lender. Identical industry
    # string to AXP/COF above.
    assert classify_company_type("Financial Services", "Financial - Credit Services", "MA") == "Standard"


def test_credit_services_non_lender_reverts_to_standard_visa():
    # V: netInterestIncome -1.5% of revenue -- confirmed the specific
    # regression case (Step 1's Net-Interest-Income revenue swap produced a
    # nonsensical near-zero/negative "revenue" series once V was
    # reclassified as Bank; this override keeps V at Standard instead).
    assert classify_company_type("Financial Services", "Financial - Credit Services", "V") == "Standard"


def test_credit_services_non_lender_reverts_to_standard_examples():
    for ticker in ("GPN", "PYPL"):
        assert classify_company_type("Financial Services", "Financial - Credit Services", ticker) == "Standard"


def test_capital_markets_no_overrides_needed():
    # Every "Financial - Capital Markets" ticker checked (GS 10.8%, MS 8.7%,
    # RJF 13.5%, HOOD 33.8%, SCHW 42.5%) turned out to be a genuine lender
    # with material net-interest income -- no override list needed for this
    # keyword.
    for ticker in ("GS", "MS", "RJF", "HOOD"):
        assert classify_company_type("Financial Services", "Financial - Capital Markets", ticker) == "Bank"
