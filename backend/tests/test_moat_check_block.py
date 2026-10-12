"""pipeline/moat_check_block.py (docs/specs/moat-check.md, step 2): the blind data block. Fixed key set, no rating anywhere, three cache
tables read and nothing written, the explicit net-margin-only rule per bucket (real FMP labels), the chart window choice, the refusals, and
the screen-only cache dates. Throwaway database files only."""

import hashlib
import json
from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import pipeline.moat_check_block as block_mod
from core.models import FundamentalsCache, LongHistoryBars, MoatCheck, SharedBarsCache, TickerMoat, TickerScore

FETCHED = datetime(2026, 10, 7, 14, 0)


def profile_row(ticker="PM", industry="Tobacco", sector="Consumer Defensive", **flags):
    body = {"symbol": ticker, "companyName": f"{ticker} Corp", "sector": sector, "industry": industry, "isEtf": False, "isFund": False, **flags}
    return FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=FETCHED, raw_json=json.dumps([body]))


def income_row(ticker="PM", years=(2022, 2023, 2024, 2025), gross=True):
    rows = []
    for year in years:
        row = {"date": f"{year}-12-31", "fiscalYear": str(year), "revenue": 1000.0, "netIncome": 100.0 + (year - 2022) * 10}
        if gross:
            row["grossProfit"] = 600.0
        rows.append(row)
    return FundamentalsCache(ticker=ticker, statement_type="income_statement", period="annual", fetched_at=FETCHED, raw_json=json.dumps(rows))


def shared_bars(ticker="PM", n=1300, start="2021-10-11"):
    index = pd.bdate_range(start=start, periods=n)
    return [
        SharedBarsCache(ticker=ticker, interval="1d", bar_time=ts.to_pydatetime(), open=100 + i * 0.1, high=101 + i * 0.1, low=99 + i * 0.1,
                        close=100 + i * 0.1, volume=1000, fetched_at=FETCHED)
        for i, ts in enumerate(index)
    ]


def long_bars(ticker="PM", n=2500, start="2016-10-11"):
    index = pd.bdate_range(start=start, periods=n)
    return [
        LongHistoryBars(ticker=ticker, bar_time=ts.to_pydatetime(), open=50 + i * 0.05, high=51 + i * 0.05, low=49 + i * 0.05,
                        close=50 + i * 0.05, volume=1000, fetched_at=FETCHED)
        for i, ts in enumerate(index)
    ]


@pytest.fixture
def db(tmp_path):
    """A throwaway FILE database (main() opens it mode=ro) plus its path."""
    path = tmp_path / "block.db"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    yield engine, path
    engine.dispose()


def seed(engine, *rows):
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def build(engine, ticker="PM"):
    with Session(engine) as session:
        return block_mod.build_block(session, ticker)


# --- the block: key set, no rating, three tables, read-only ----------------------------------------------------------------------


def test_the_block_has_exactly_the_fixed_keys(db):
    engine, _ = db
    seed(engine, profile_row(), income_row(), *shared_bars())
    block, _ = build(engine)
    assert tuple(block) == block_mod.BLOCK_KEYS
    assert block["ticker"] == "PM" and block["name"] == "PM Corp" and block["sector"] == "Consumer Defensive" and block["industry"] == "Tobacco"
    assert set(block["price_chart"]) == {"window", "years", "description", "year_end_closes"}


def test_no_rating_score_or_verdict_is_anywhere_in_the_block(db):
    engine, path = db
    seed(
        engine, profile_row(), income_row(), *shared_bars(),
        TickerMoat(ticker="PM", moat="wide_moat", updated_at=FETCHED),
        TickerScore(ticker="PM", moat="wide_moat", overall_score=88, overall_verdict="Strong Pass", computed_at=FETCHED),
        MoatCheck(ticker="PM", checked_at=FETCHED, criteria_version="v", status="stable", rating="wide_moat", pass1_rating="wide_moat",
                  pass2_rating="wide_moat", evidence_confidence="High", proof_basis="independent", pass1_json="{}", pass2_json="{}"),
    )
    out = path.parent / "block.json"
    assert block_mod.main(["PM", "--out", str(out)], db_path=path) == 0
    text = out.read_text().lower()
    for leak in ("wide_moat", "narrow_moat", "no_moat", "moat", "strong pass", "88", "overall", "verdict"):
        assert leak not in text, leak


def test_only_the_three_cache_tables_are_read_and_nothing_is_written(db):
    engine, _ = db
    seed(engine, profile_row(), income_row(), *shared_bars(), TickerMoat(ticker="PM", moat="wide_moat", updated_at=FETCHED))
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    build(engine)
    assert statements and all(s.lstrip().startswith("select") for s in statements)
    joined = " ".join(statements)
    for table in ("tickermoat", "tickerscore", "moatcheck"):
        assert table not in joined
    assert "fundamentalscache" in joined and "sharedbarscache" in joined and "longhistorybars" in joined


def test_main_leaves_the_database_file_untouched_and_writes_only_the_output(db, tmp_path):
    engine, path = db
    seed(engine, profile_row(), income_row(), *shared_bars())
    engine.dispose()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    out = tmp_path / "out" / "block.json"
    out.parent.mkdir()
    assert block_mod.main(["pm", "--out", str(out)], db_path=path) == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert json.loads(out.read_text())["ticker"] == "PM"
    assert sorted(p.name for p in path.parent.iterdir() if p.name.startswith("block.db")) == ["block.db"]  # no -wal/-journal left behind


def test_the_module_never_uses_the_rating_or_score_tables_or_the_network():
    import ast

    tree = ast.parse(open(block_mod.__file__).read())
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert not used & {"TickerMoat", "TickerScore", "MoatCheck", "compute_ticker_score", "init_db", "fmp_client", "get_ticker_moat"}


# --- net margin only: one test per bucket, real labels ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ticker, industry",
    [
        ("USB", "Banks - Regional"),
        ("JPM", "Banks - Diversified"),
        ("BAC", "Banks - Diversified"),
        ("BRK-B", "Insurance - Diversified"),
        ("MET", "Insurance - Life"),
        ("AIG", "Insurance - Diversified"),
        ("AJG", "Insurance - Brokers"),
        ("TRV", "Insurance - Property & Casualty"),
        ("RGA", "Insurance - Reinsurance"),
        ("GS", "Financial - Capital Markets"),
        ("SCHW", "Financial - Capital Markets"),
        ("MS", "Financial - Capital Markets"),
        ("BLK", "Asset Management"),
        ("BX", "Asset Management"),
        ("KKR", "Asset Management"),
        ("XYZ", "Asset Management - Global"),
        ("XYZ", "Asset Management - Bonds"),
        ("XYZ", "Asset Management - Cryptocurrency"),
        ("XYZ", "Asset Management - Leveraged"),
    ],
)
def test_net_margin_only_industries(ticker, industry):
    assert block_mod.net_margin_only(industry, ticker) is True


@pytest.mark.parametrize("ticker", ["AXP", "COF", "SYF", "DFS", "ALLY"])
def test_the_named_card_lenders_are_net_only_though_their_industry_is_credit_services(ticker):
    assert block_mod.net_margin_only("Financial - Credit Services", ticker) is True


@pytest.mark.parametrize("ticker", ["V", "MA", "PYPL"])
def test_payment_networks_keep_gross_and_net(ticker):
    assert block_mod.net_margin_only("Financial - Credit Services", ticker) is False


@pytest.mark.parametrize("ticker", ["SPGI", "CME", "ICE"])
def test_exchange_and_data_companies_keep_gross_and_net(ticker):
    assert block_mod.net_margin_only("Financial - Data & Stock Exchanges", ticker) is False


@pytest.mark.parametrize(
    "ticker, industry",
    [
        ("XYZ", "Investment - Banking & Investment Services"),  # seen, deliberately not on the list
        ("XYZ", "Asset Managers"),  # a lookalike, not the label or a "Asset Management - " variant
        ("XYZ", "Asset Management Software"),
        ("XYZ", "Insurers"),  # not "Insurance"
        ("XYZ", "Tobacco"),
        ("XYZ", "Semiconductors"),
        ("XYZ", "Space Tourism"),  # an industry never seen before
        ("XYZ", ""),
        ("XYZ", None),
        ("XYZ", "Banking"),  # not "Banks"
    ],
)
def test_everything_else_and_any_unseen_industry_gets_gross_and_net(ticker, industry):
    assert block_mod.net_margin_only(industry, ticker) is False


def test_the_ticker_list_is_matched_after_normalisation():
    assert block_mod.net_margin_only("Financial - Credit Services", "axp") is True


def test_a_net_only_company_gets_net_margins_and_the_matching_note(db):
    engine, _ = db
    seed(engine, profile_row("USB", industry="Banks - Regional", sector="Financial Services"), income_row("USB"), *shared_bars("USB"))
    block, info = build(engine, "USB")
    assert block["annual_margins"]["2025"] == {"net_margin": 0.13}
    assert all("gross_margin" not in v for v in block["annual_margins"].values())
    assert block["margins_note"].startswith("Annual net margin from")
    assert info["margin_rule"].startswith("net margin only")


def test_a_payment_network_gets_gross_and_net_with_real_labels(db):
    engine, _ = db
    seed(engine, profile_row("V", industry="Financial - Credit Services", sector="Financial Services"), income_row("V"), *shared_bars("V"))
    block, _ = build(engine, "V")
    assert block["annual_margins"]["2025"] == {"gross_margin": 0.6, "net_margin": 0.13}
    assert block["margins_note"].startswith("Annual gross and net margin from")


def test_a_card_lender_in_the_same_industry_gets_net_only(db):
    engine, _ = db
    seed(engine, profile_row("AXP", industry="Financial - Credit Services", sector="Financial Services"), income_row("AXP"), *shared_bars("AXP"))
    block, _ = build(engine, "AXP")
    assert all(set(v) == {"net_margin"} for v in block["annual_margins"].values())


def test_an_unseen_industry_defaults_to_gross_and_net_in_the_block(db):
    engine, _ = db
    seed(engine, profile_row("NEW", industry="Space Tourism"), income_row("NEW"), *shared_bars("NEW"))
    block, _ = build(engine, "NEW")
    assert all(set(v) == {"gross_margin", "net_margin"} for v in block["annual_margins"].values())


def test_a_missing_gross_profit_is_none_not_an_error(db):
    engine, _ = db
    seed(engine, profile_row(), income_row(gross=False), *shared_bars())
    assert build(engine)[0]["annual_margins"]["2024"] == {"gross_margin": None, "net_margin": 0.12}


def test_a_year_with_no_revenue_is_skipped():
    rows = [{"date": "2024-12-31", "fiscalYear": "2024", "revenue": 0, "netIncome": 5}, {"date": "2025-12-31", "fiscalYear": "2025", "revenue": 200, "netIncome": 20}]
    assert block_mod.annual_margins(rows, True) == {"2025": {"net_margin": 0.1}}


# --- the chart -------------------------------------------------------------------------------------------------------------------


def test_ten_year_bars_are_used_when_there_are_enough(db):
    engine, _ = db
    seed(engine, profile_row(), income_row(), *long_bars(), *shared_bars())
    chart = build(engine)[0]["price_chart"]
    assert chart["window"] == "10-year daily bars" and chart["description"].startswith("10-year daily bars from 2016-10-11")


def test_five_year_shared_bars_are_the_fallback(db):
    engine, _ = db
    seed(engine, profile_row(), income_row(), *long_bars(n=100), *shared_bars())
    chart = build(engine)[0]["price_chart"]
    assert chart["window"] == "5-year daily bars" and chart["description"].startswith("5-year daily bars from 2021-10-11")


def test_the_chart_description_and_year_end_closes():
    dates = [d.date().isoformat() for d in pd.bdate_range("2024-01-02", periods=300)]
    closes = [100.0 + i for i in range(150)] + [250.0 - i for i in range(150)]
    chart = block_mod.describe_chart(dates, closes, "5-year")
    assert "close 100.00 -> 101.00" in chart["description"] and "Maximum drawdown -60%" in chart["description"]
    assert f"(peak {dates[150]} to trough {dates[-1]})" in chart["description"]
    assert "under a year" not in chart["description"]  # more than a year of bars
    assert set(chart["year_end_closes"]) == {"2024", "2025"}


def test_under_a_year_of_bars_says_so():
    dates = [d.date().isoformat() for d in pd.bdate_range("2026-01-02", periods=60)]
    chart = block_mod.describe_chart(dates, [100.0 + i for i in range(60)], "5-year")
    assert "not available (under a year of bars)" in chart["description"]


# --- refusals --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows, fragment",
    [
        ((), "no cached profile"),
        ((profile_row(isEtf=True), income_row(), *shared_bars()), "ETF or fund"),
        ((profile_row(isFund=True), income_row(), *shared_bars()), "ETF or fund"),
        ((profile_row(), *shared_bars()), "no cached annual income statement"),
        ((profile_row(), income_row(years=()), *shared_bars()), "no cached annual income statement"),
        ((profile_row(), income_row()), "fewer than 2 cached daily bars"),
        ((profile_row(), income_row(), *shared_bars(n=1)), "fewer than 2 cached daily bars"),
    ],
)
def test_the_block_is_refused_with_a_reason(db, tmp_path, capsys, rows, fragment):
    engine, path = db
    seed(engine, *rows)
    out = tmp_path / "block.json"
    assert block_mod.main(["PM", "--out", str(out)], db_path=path) == 2
    assert fragment in capsys.readouterr().err and not out.exists()


# --- screen-only cache dates -----------------------------------------------------------------------------------------------------


def test_cache_dates_are_printed_to_the_screen_and_not_added_to_the_block(db, tmp_path, capsys):
    engine, path = db
    seed(engine, profile_row(), income_row(), *shared_bars())
    out = tmp_path / "block.json"
    assert block_mod.main(["PM", "--out", str(out)], db_path=path) == 0
    printed = capsys.readouterr().out
    block = json.loads(out.read_text())
    assert "statement fiscal dates read: 2022-12-31 to 2025-12-31 (4 years)" in printed
    last = pd.bdate_range(start="2021-10-11", periods=1300)[-1].date().isoformat()
    assert f"last bar date: {last}" in printed and "margins: gross and net margin (industry: Tobacco)" in printed
    assert tuple(block) == block_mod.BLOCK_KEYS  # no key was added for them
    assert "-12-31" not in out.read_text()  # no fiscal date string in the block
