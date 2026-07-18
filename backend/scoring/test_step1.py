from scoring.step1 import score_step1

GROWING = [100, 110, 121, 133, 146]
DECLINING = [146, 133, 121, 110, 100]
STABLE_MARGINS = [40, 41, 40, 42, 43]
NET_MARGINS_STABLE = [20, 20.5, 20, 21, 21.5]


def test_strong_pass_all_growing():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["score"] == 100
    assert result["verdict"] == "Strong Pass"
    assert result["components"]["cfo"]["score"] == 100
    assert result["weights"] == {"revenue": 0.30, "net_income": 0.30, "cfo": 0.30, "margins": 0.10}


def test_fail_all_declining():
    result = score_step1(
        revenue=DECLINING,
        net_income=DECLINING,
        operating_income=DECLINING,
        cfo=DECLINING,
        gross_margin=list(reversed(STABLE_MARGINS)),
        net_margin=list(reversed(NET_MARGINS_STABLE)),
        cfo_exempt=False,
    )
    assert result["score"] < 50
    assert result["verdict"] == "Fail"
    assert result["components"]["revenue"]["score"] == 0
    assert result["components"]["cfo"]["score"] == 0


def test_cfo_exemption_redistributes_weights():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=None,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=True,
    )
    assert result["weights"] == {"revenue": 0.45, "net_income": 0.45, "cfo": 0.0, "margins": 0.10}
    assert result["components"]["cfo"] is None
    assert result["score"] == 100


def test_net_income_backup_rule_uses_operating_income():
    # Net income is badly inconsistent (score <= 40) but operating income is clean.
    weak_net_income = [100, 60, 90, 55, 95]
    result = score_step1(
        revenue=GROWING,
        net_income=weak_net_income,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["components"]["net_income"]["used_operating_income_backup"] is True
    # min(80, max(weak_ni_score, 100)) == 80
    assert result["components"]["net_income"]["score"] == 80


def test_net_income_backup_not_used_when_score_above_threshold():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["components"]["net_income"]["used_operating_income_backup"] is False


def test_score_clamped_to_valid_range():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert 0 <= result["score"] <= 100
