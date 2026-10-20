"""GET /api/opportunities/scorecard{,/flags,/picks,/outcomes} over a throwaway database: route order, the gate end to end, version and weights
filters, every exclusion, the flag denominators, the picks proxy, the row-level audit, the cache key, an empty database, read-only behaviour and
roles. The aggregation itself is covered in test_opportunity_scorecard.py."""

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import data.opportunity_data as od
import data.opportunity_scorecard_data as sd
from core.main import app
from core.models import (
    OpportunityDailyFlag,
    OpportunityDailyRun,
    OpportunityFlagOutcome,
    OpportunityOutcome,
    OpportunityOutcomeRun,
    OpportunityPick,
    OpportunityPoolOutcome,
    OpportunityRun,
    OpportunitySnapshotRow,
)
from scoring import opportunity_rules as rules
from scoring import opportunity_triggers as trig

NOW = datetime(2026, 10, 10, 4, 0)
BASE = date(2026, 1, 2)
D1, D2, D3 = trig.TRIGGER_D1, trig.TRIGGER_D2, trig.TRIGGER_D3


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(od, "engine", engine)
    monkeypatch.setattr(sd, "engine", engine)
    sd.clear_cache()
    yield engine
    sd.clear_cache()


def as_of(i: int) -> date:
    return BASE + timedelta(days=7 * i)


def outcome(run_id, ticker, horizon, status="complete", ret=0.05, spy=0.01, sector=0.02, rv=rules.RULES_VERSION, gap=False, stop=False, **kw):
    done = status in ("complete", "censored")
    return OpportunityOutcome(
        run_id=run_id, ticker=ticker, horizon=horizon, status=status, forward_return=ret if done else None, spy_return=spy if done else None,
        excess_vs_spy=(ret - spy) if done else None, sector_etf="XLK", sector_return=sector if done else None,
        excess_vs_sector=(ret - sector) if done else None, worst_move=-0.03 if done else None, max_drawdown=-0.02 if done else None,
        stop_hit=stop, stop_fill_return=-0.10 if stop else None, entry_gap_pct=0.30 if gap else 0.0, entry_gap_flag=gap, rules_version=rv,
        computed_at=NOW, **kw,
    )


def seed_run(engine, i, *, weights=8, rules_version=rules.RULES_VERSION, names=None, horizons=(5,), status="complete", pool=0, **okw):
    """A weekly run `i` weeks after BASE with `names` = [(ticker, list, tier, rule_ids, tags)] (default 8 Momentum Quality names), each with
    outcome rows at `horizons`, plus `pool` unlisted Momentum Quality pool outcome rows."""
    names = names if names is not None else [(f"N{i}{j}", "momentum", "quality", [rules.RULE_A], {}) for j in range(8)]
    with Session(engine) as s:
        run = OpportunityRun(
            kind="weekly", as_of_date=as_of(i), last_bar_date=as_of(i), universe_size=600, rules_hash="h", rules_version=rules_version,
            score_formula_version=6, weights_version=weights, created_at=NOW,
        )
        s.add(run)
        s.flush()
        for order, (ticker, lst, tier, rule_ids, tags) in enumerate(names, start=1):
            s.add(OpportunitySnapshotRow(run_id=run.id, list_name=lst, ticker=ticker, tier=tier, list_order=order, rule_ids_json=json.dumps(rule_ids), tags_json=json.dumps(tags)))
            for h in horizons:
                s.add(outcome(run.id, ticker, h, status=status, rv=rules_version, **okw))
        for k in range(pool):
            for h in horizons:
                s.add(OpportunityPoolOutcome(
                    run_id=run.id, ticker=f"P{i}{k}", horizon=h, status="complete", tier="quality", assigned_list="momentum", leveraged=False,
                    forward_return=0.02, spy_return=0.01, excess_vs_spy=0.01, sector_return=0.01, excess_vs_sector=0.01, rules_version=rules_version, computed_at=NOW,
                ))
        s.commit()
        return run.id


def seed_updater_run(engine, spy_date=date(2026, 10, 19)):
    with Session(engine) as s:
        s.add(OpportunityOutcomeRun(started_at=NOW, finished_at=NOW, status="success", spy_last_bar_date=spy_date, message="ok"))
        s.commit()


def get(path, **params):
    with TestClient(app) as client:
        r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def cell(body, key, h="5", b="spy"):
    return next(g for g in body["groups"] if g["key"] == key)["cells"][h][b]


# --- routing, empty database --------------------------------------------------------------------------------------------------------


def test_scorecard_routes_come_before_the_dated_route(engine):
    seed_run(engine, 0)
    with TestClient(app) as client:
        for path in ("/scorecard", "/scorecard/flags", "/scorecard/picks", "/scorecard/outcomes"):
            r = client.get(f"/api/opportunities{path}")
            assert r.status_code == 200, (path, r.text)  # never a 422 from {as_of_date}
        assert client.get(f"/api/opportunities/{as_of(0).isoformat()}").status_code == 200
        assert client.get("/api/opportunities/not-a-date").status_code == 422


def test_an_empty_database_answers_every_endpoint(engine):
    body = get("/api/opportunities/scorecard")
    assert body["has_data"] is False and body["cohorts"] == [] and body["latest"]["outcomes_spy_bar"] is None
    assert cell(body, "momentum")["n_complete"] == 0 and cell(body, "momentum")["state"] == "too_early"
    flags = get("/api/opportunities/scorecard/flags")
    assert flags["has_data"] is False and flags["ledger"] == [] and flags["triggers"]["D1"]["flagged"] == 0
    picks = get("/api/opportunities/scorecard/picks")
    assert picks["empty"] is True and picks["count"] == 0 and picks["label"] == "Priced from the list date, not your add date"
    out = get("/api/opportunities/scorecard/outcomes")
    assert out["rows"] == [] and out["total"] == 0


# --- the gate end to end ---------------------------------------------------------------------------------------------------------


def test_gate_below_early_and_above_with_synthetic_cohorts(engine):
    for i in range(2):
        seed_run(engine, i)  # 2 cohorts x 8 rows = 16 rows
    body = get("/api/opportunities/scorecard")
    assert cell(body, "momentum")["state"] == "too_early" and cell(body, "momentum")["values"] is None
    for i in range(2, 4):
        seed_run(engine, i)  # 4 cohorts, 32 rows
    sd.clear_cache()
    c = cell(get("/api/opportunities/scorecard"), "momentum")
    assert c["state"] == "early" and c["n_complete"] == 32 and c["cohorts"] == 4
    assert c["values"]["median_excess"] == pytest.approx(0.04) and c["values"]["cohorts_positive"] == 4
    for i in range(4, 8):
        seed_run(engine, i)  # 8 cohorts, 64 rows
    sd.clear_cache()
    c = cell(get("/api/opportunities/scorecard"), "momentum")
    assert c["state"] == "ok" and c["n_complete"] == 64 and c["cohorts"] == 8


def test_every_exclusion_is_counted_with_its_bucket(engine):
    names = [(f"C{j}", "momentum", "quality", [rules.RULE_A], {}) for j in range(3)] + [("LEV", "momentum", "etf", [rules.RULE_A], {"leveraged": 3})]
    rid = seed_run(engine, 0, names=names, horizons=(5,))
    with Session(engine) as s:
        s.add(outcome(rid, "PEND", 5, status="pending"))
        s.add(outcome(rid, "CENS", 5, status="censored", ret=-0.5, spy=0.0))
        s.add(outcome(rid, "GAPP", 5, gap=True))
        for t in ("PEND", "CENS", "GAPP"):
            s.add(OpportunitySnapshotRow(run_id=rid, list_name="momentum", ticker=t, tier="quality", list_order=9, rule_ids_json="[]"))
        s.commit()
    body = get("/api/opportunities/scorecard")
    c = cell(body, "momentum")
    assert (c["n_complete"], c["n_pending"], c["n_censored"], c["n_entry_gap"]) == (3, 1, 1, 1)
    assert cell(body, "momentum:leveraged")["n_complete"] == 1 and cell(body, "momentum:etf")["n_complete"] == 0
    assert body["excluded"]["by_horizon"]["5"] == {"complete": 3, "pending": 1, "censored": 1, "entry_gap": 1, "leveraged": 1}
    audit = get("/api/opportunities/scorecard/outcomes")
    assert sorted(r["bucket"] for r in audit["rows"] if r["horizon"] == 5) == sorted(["complete"] * 3 + ["censored", "entry_gap", "leveraged", "pending"])


def test_pool_baseline_is_matched_and_gated_with_the_cell(engine):
    for i in range(8):
        seed_run(engine, i, pool=10)
    c = cell(get("/api/opportunities/scorecard"), "momentum:quality")
    assert c["pool"]["n_complete"] == 80 and c["pool"]["values"]["median_excess"] == pytest.approx(0.01)
    assert c["listed_minus_pool"]["median_excess"] == pytest.approx(0.03)


# --- versions ----------------------------------------------------------------------------------------------------------------------


def test_rows_of_another_rules_version_are_excluded_and_counted_not_merged(engine):
    for i in range(3):
        seed_run(engine, i)  # current rules version
    for i in range(3, 5):
        seed_run(engine, i, rules_version="1")
    body = get("/api/opportunities/scorecard")
    assert cell(body, "momentum")["n_complete"] == 24 and body["excluded"]["other_rules_version_rows"] == 16
    assert body["versions"]["available"]["rules"] == ["1", rules.RULES_VERSION]
    old = get("/api/opportunities/scorecard", rules_version="1")
    assert cell(old, "momentum")["n_complete"] == 16 and old["excluded"]["other_rules_version_rows"] == 24


def test_weights_filter_and_the_mixed_weights_note(engine):
    for i in range(3):
        seed_run(engine, i, weights=8)
    for i in range(3, 6):
        seed_run(engine, i, weights=9)
    body = get("/api/opportunities/scorecard")
    q = cell(body, "momentum:quality")
    assert q["n_complete"] == 48 and q["mixed_weights"] is True and q["weights_versions"] == [8, 9]  # default: all, NOT split
    only8 = get("/api/opportunities/scorecard", weights_version=8)
    assert cell(only8, "momentum:quality")["n_complete"] == 24 and cell(only8, "momentum:quality")["mixed_weights"] is False
    assert only8["excluded"]["cohorts_other_weights_version"] == 3
    assert body["versions"]["available"]["weights"] == [8, 9]


# --- flags --------------------------------------------------------------------------------------------------------------------------


def seed_flag(engine, run_id, cohort, ticker, trigger_id, list_name, flag_date, at_ma=None, outcomes=(), version=trig.TRIGGERS_VERSION):
    with Session(engine) as s:
        f = OpportunityDailyFlag(
            list_as_of_date=cohort, ticker=ticker, trigger_id=trigger_id, trigger_version=version, list_name=list_name, tier="quality",
            flag_date=flag_date, observed_at=NOW, inputs_json=json.dumps({"list_row": {"already_at_ma_on_list": at_ma}} if at_ma is not None else {}),
        )
        s.add(f)
        s.flush()
        for h, status in outcomes:
            s.add(OpportunityFlagOutcome(
                flag_id=f.id, ticker=ticker, trigger_id=trigger_id, flag_date=flag_date, horizon=h, status=status, forward_return=0.10 if status == "complete" else None,
                spy_return=0.01 if status == "complete" else None, excess_vs_spy=0.09 if status == "complete" else None, trigger_version=version, computed_at=NOW,
            ))
        s.commit()


def test_flag_counts_denominators_ledger_and_window_open(engine):
    reversal = [("R1", "reversal", "quality", [rules.RULE_B2], {}), ("R2", "reversal", "quality", [rules.RULE_B2], {}), ("R3", "reversal", "quality", [rules.RULE_B2], {}),
                ("R4", "reversal", "quality", [rules.RULE_B2], {}), ("M1", "momentum", "quality", [rules.RULE_A], {}), ("M2", "momentum", "quality", [rules.RULE_A], {})]
    rid0 = seed_run(engine, 0, names=reversal)
    seed_run(engine, 1, names=reversal)  # the later run: cohort 0's flag window is closed, cohort 1's is open
    c0, c1 = as_of(0), as_of(1)
    seed_flag(engine, rid0, c0, "R1", D1, "reversal", c0 + timedelta(days=3), outcomes=[(5, "complete"), (10, "pending")])
    seed_flag(engine, rid0, c0, "R1", D2, "reversal", c0 + timedelta(days=4), outcomes=[(5, "pending")])
    seed_flag(engine, rid0, c0, "M1", D3, "momentum", c0 + timedelta(days=3), at_ma=True, outcomes=[(5, "complete")])
    seed_flag(engine, rid0, c0, "M2", D3, "momentum", c0 + timedelta(days=3), at_ma=False, outcomes=[(5, "complete")])
    seed_flag(engine, rid0, c1, "R2", D1, "reversal", c1 + timedelta(days=3))  # no outcome rows yet
    seed_flag(engine, rid0, c0, "R4", D1, "reversal", c0 + timedelta(days=3), version="0")  # another trigger version: excluded
    with Session(engine) as s:
        s.add(OpportunityDailyRun(
            started_at=NOW, status="success", list_as_of_date=c0, not_covered_json=json.dumps({D1: ["R3", "R2"]}),
            incomplete_json=json.dumps({D1: {"R4": "upstream_job_not_successful"}}),
        ))
        s.commit()
    body = get("/api/opportunities/scorecard/flags")
    d1 = body["triggers"]["D1"]
    # cohort 0: eligible R1..R4; flagged R1; not covered R3 (R2 too); incomplete R4 -> unflagged = R2? (R2 is not covered) -> 0
    c0row = next(p for p in d1["per_cohort"] if p["cohort"] == c0.isoformat())
    assert (c0row["eligible"], c0row["flagged"], c0row["not_covered"], c0row["incomplete"], c0row["unflagged"]) == (4, 1, 2, 1, 0)
    assert c0row["window_open"] is False
    c1row = next(p for p in d1["per_cohort"] if p["cohort"] == c1.isoformat())
    assert c1row["window_open"] is True and c1row["flagged"] == 1
    assert d1["cohorts_window_open"] == 1 and d1["flagged_in_open_cohorts"] == 1 and body["excluded"]["other_trigger_version_flags"] == 1
    assert d1["cells"]["5"]["spy"]["flagged"]["n_complete"] == 1 and d1["cells"]["5"]["spy"]["flagged"]["n_unpriced"] == 1
    d3 = body["triggers"]["D3"]
    assert d3["split"]["already_at_ma_on_list"]["flagged"] == 1 and d3["split"]["not_at_ma_on_list"]["flagged"] == 1
    assert body["any_flag"]["flagged_names"] == 4  # R1 (D1+D2 -> once), M1, M2, R2
    assert body["comparator_label"] == "Not a controlled comparison"
    r1 = [r for r in body["ledger"] if r["ticker"] == "R1"]
    assert {r["trigger"] for r in r1} == {"D1", "D2"} and r1[0]["horizons"]["5"] is not None
    assert all(r["trigger_id"] != "x" for r in body["ledger"]) and len(body["ledger"]) == 5  # the other-version flag is not in the ledger
    sel = get("/api/opportunities/scorecard/flags", triggers_version="0")
    assert sel["triggers"]["D1"]["flagged"] == 1


def test_flag_leveraged_names_are_left_out_of_the_aggregates(engine):
    names = [("SOXL", "reversal", "etf", [rules.RULE_B2], {"leveraged": 3}), ("R1", "reversal", "quality", [rules.RULE_B2], {})]
    rid = seed_run(engine, 0, names=names)
    seed_flag(engine, rid, as_of(0), "SOXL", D2, "reversal", as_of(0) + timedelta(days=3), outcomes=[(5, "complete")])
    body = get("/api/opportunities/scorecard/flags")
    assert body["triggers"]["D2"]["eligible"] == 1 and body["triggers"]["D2"]["flagged"] == 0
    assert [r["ticker"] for r in body["ledger"]] == ["SOXL"] and body["ledger"][0]["leveraged"] is True  # still visible in the ledger


# --- picks, audit --------------------------------------------------------------------------------------------------------------------


def test_picks_are_priced_from_the_list_date_and_labelled(engine):
    seed_run(engine, 0)
    with Session(engine) as s:
        s.add(OpportunityPick(as_of_date=as_of(0), ticker="N00", picked_at=NOW, source="opportunities_page"))
        s.add(OpportunityPick(as_of_date=as_of(5), ticker="GONE", picked_at=NOW, source="opportunities_page"))
        s.commit()
    body = get("/api/opportunities/scorecard/picks")
    assert body["empty"] is False and body["count"] == 2 and body["unmatched"] == 1 and body["label"] == "Priced from the list date, not your add date"
    assert body["cells"]["5"]["spy"]["n_complete"] == 1 and body["cells"]["5"]["spy"]["values"] is None  # one pick: below the gate


def test_outcome_audit_pages_and_filters(engine):
    seed_run(engine, 0, horizons=(5, 10))
    page = get("/api/opportunities/scorecard/outcomes", limit=5)
    assert page["total"] == 16 and len(page["rows"]) == 5 and page["truncated"] is True
    h10 = get("/api/opportunities/scorecard/outcomes", horizon=10)
    assert h10["total"] == 8 and {r["horizon"] for r in h10["rows"]} == {10}
    assert get("/api/opportunities/scorecard/outcomes", source="pool")["rows"] == []
    with TestClient(app) as client:
        assert client.get("/api/opportunities/scorecard/outcomes", params={"source": "nope"}).status_code == 422
        assert client.get("/api/opportunities/scorecard/outcomes", params={"limit": 0}).status_code == 422
        assert client.get("/api/opportunities/scorecard/outcomes", params={"horizon": 7}).status_code == 422


# --- cache, read-only, roles ------------------------------------------------------------------------------------------------------------


def test_the_cache_is_keyed_on_the_latest_updater_and_daily_run_ids(engine, monkeypatch):
    seed_run(engine, 0)
    seed_updater_run(engine)
    calls = []
    real = sd._compute_scorecard
    monkeypatch.setattr(sd, "_compute_scorecard", lambda session, sel: (calls.append(1), real(session, sel))[1])
    get("/api/opportunities/scorecard")
    get("/api/opportunities/scorecard")
    assert len(calls) == 1  # the second request is served from the cache
    get("/api/opportunities/scorecard", rules_version="1")
    assert len(calls) == 2  # a different parameter set is its own entry
    seed_updater_run(engine, date(2026, 10, 20))  # the 03:40 job wrote a new run id
    body = get("/api/opportunities/scorecard")
    assert len(calls) == 3 and body["latest"]["outcomes_spy_bar"] == "2026-10-20"
    with Session(engine) as s:
        s.add(OpportunityDailyRun(started_at=NOW, status="noop"))
        s.commit()
    get("/api/opportunities/scorecard")
    assert len(calls) == 4  # a new daily-flag run id also invalidates it


def test_reading_writes_nothing(engine):
    seed_run(engine, 0, pool=3)
    seed_updater_run(engine)
    writes = []

    @event.listens_for(engine, "before_cursor_execute")
    def _watch(conn, cursor, statement, *a):  # noqa: ANN001
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}:
            writes.append(statement)

    for path in ("", "/flags", "/picks", "/outcomes"):
        get(f"/api/opportunities/scorecard{path}")
    get("/api/opportunities/scorecard/outcomes", source="flags")
    get("/api/opportunities/scorecard/outcomes", source="pool")
    assert writes == []


@pytest.mark.parametrize("path", ["", "/flags", "/picks", "/outcomes"])
@pytest.mark.parametrize("verb", ["post", "put", "patch", "delete"])
def test_no_mutating_verb_is_accepted(engine, verb, path):
    with TestClient(app) as client:
        assert getattr(client, verb)(f"/api/opportunities/scorecard{path}").status_code in (404, 405)


@pytest.mark.auth("viewer")
def test_a_viewer_can_read_the_scorecard(engine):
    seed_run(engine, 0)
    for path in ("", "/flags", "/picks", "/outcomes"):
        get(f"/api/opportunities/scorecard{path}")


@pytest.mark.auth("anonymous")
def test_anonymous_gets_401(engine):
    with TestClient(app) as client:
        for path in ("", "/flags", "/picks", "/outcomes"):
            assert client.get(f"/api/opportunities/scorecard{path}").status_code == 401
