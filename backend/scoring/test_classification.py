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
