from sqlmodel import Session, SQLModel, create_engine

from core.schemas import Step3ManualParams
from data.custom_valuation_data import (
    activate_ticker_custom_valuation,
    deactivate_ticker_custom_valuation,
    delete_ticker_custom_valuation,
    get_ticker_custom_valuation,
    parse_custom_valuation_params,
    set_ticker_custom_valuation,
)

# custom_valuation_data.py takes `session` as a parameter rather than
# importing its own module-level `engine` (mirrors moat.py) -- so unlike
# step2_data.py/step3_data.py/ticker_summary.py etc, no monkeypatch is
# needed here at all, a bare in-memory engine is sufficient and can never
# trip conftest.py's real-DB write guard.
def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_get_returns_none_when_no_row_saved():
    engine = _engine()
    with Session(engine) as session:
        assert get_ticker_custom_valuation(session, "AAPL") is None


def test_set_creates_an_inactive_row():
    engine = _engine()
    with Session(engine) as session:
        row = set_ticker_custom_valuation(session, "aapl", "DCF", '{"current_value": 1.0}')
    assert row.ticker == "AAPL"
    assert row.method == "DCF"
    assert row.parameters_json == '{"current_value": 1.0}'
    assert row.is_active is False
    assert row.saved_at is not None


def test_set_upserts_without_touching_is_active():
    engine = _engine()
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "AAPL", "DCF", "{}")
        activate_ticker_custom_valuation(session, "AAPL")
        # Re-saving (editing inputs) an already-active row must leave it
        # active -- there's no draft/live split, one row is the live row.
        updated = set_ticker_custom_valuation(session, "AAPL", "DFCF", '{"a": 1}')
    assert updated.method == "DFCF"
    assert updated.parameters_json == '{"a": 1}'
    assert updated.is_active is True


def test_activate_returns_none_when_no_row_saved():
    engine = _engine()
    with Session(engine) as session:
        assert activate_ticker_custom_valuation(session, "AAPL") is None


def test_activate_sets_is_active_true():
    engine = _engine()
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "AAPL", "DCF", "{}")
        row = activate_ticker_custom_valuation(session, "AAPL")
    assert row is not None
    assert row.is_active is True


def test_deactivate_sets_is_active_false_and_keeps_row():
    engine = _engine()
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "AAPL", "DCF", "{}")
        activate_ticker_custom_valuation(session, "AAPL")
        row = deactivate_ticker_custom_valuation(session, "AAPL")
        still_there = get_ticker_custom_valuation(session, "AAPL")
    assert row.is_active is False
    assert still_there is not None
    assert still_there.is_active is False


def test_deactivate_returns_none_when_no_row_saved():
    engine = _engine()
    with Session(engine) as session:
        assert deactivate_ticker_custom_valuation(session, "AAPL") is None


def test_delete_removes_row_and_reports_it_existed():
    engine = _engine()
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "AAPL", "DCF", "{}")
        existed = delete_ticker_custom_valuation(session, "AAPL")
        remaining = get_ticker_custom_valuation(session, "AAPL")
    assert existed is True
    assert remaining is None


def test_delete_returns_false_when_no_row_saved():
    engine = _engine()
    with Session(engine) as session:
        assert delete_ticker_custom_valuation(session, "AAPL") is False


def test_parse_custom_valuation_params_round_trips():
    params = Step3ManualParams(sales_per_share=10.0, projected_growth_rate=0.1, fair_psg_ratio=0.2)
    parsed = parse_custom_valuation_params(params.model_dump_json())
    assert parsed == params


def test_parse_custom_valuation_params_returns_none_on_corrupt_json():
    assert parse_custom_valuation_params("not valid json") is None
