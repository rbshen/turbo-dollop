"""data/moat_check.py + the MoatCheck table (docs/specs/moat-check.md): structural validation of a pass record, the two values derived in
code (overall threat level, confidence under company-only proof), reconciliation of two passes, append-only history, the newest-row read,
the ETF refusal, the guarantee that a check touches no rating or score, the registry / merge / backup wiring. All against throwaway
in-memory engines."""

import copy
import gzip
import json
import sqlite3
from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import data.moat_check as mc
import pipeline.merge_duplicate_ticker_identities as merge
from core.models import FundamentalsCache, MoatCheck, TickerMoat, TickerScore

T0 = datetime(2026, 10, 12, 10, 0)


def fact(text="a dated figure"):
    return {"fact": text, "source": "https://example.com/a", "date": "2026-06-01"}


def make_record(ticker="PM", rating="narrow_moat", confidence="Medium", proof="independent", threat_levels=("Moderate",)):
    return {
        "ticker": ticker,
        "criteria_version": mc.MOAT_CRITERIA_VERSION,
        "checked_date": "2026-10-12",
        "suggested_rating": rating,
        "sources_rating": {
            "brand_monopoly": "strong",
            "switching_costs": "moderate",
            "barriers_to_entry": "weak",
            "network_effect": "absent",
            "economies_of_scale": "unproven",
        },
        "source_facts": {
            "brand_monopoly": fact("share 31%"),
            "switching_costs": fact(),
            "barriers_to_entry": fact(),
            "network_effect": fact("rivals list on the same sites"),
            "economies_of_scale": None,
        },
        "moat_types": ["brand_monopoly"],
        "realistic_competitors": ["Rival Co"],
        "reading": "supported",
        "ladder_levels": [1, 2],
        "outcome_evidence": [{"level": 1, "item": "share held", "source": "https://example.com/b", "date": "2026-05", "stale": False}],
        "outcome_supporting_item": "share held",
        "margins_note": "margins stable",
        "proof_basis": proof,
        "observed_damage": [{"metric": "Net margin", "change": "from 10% to 9%", "period": "2024-2025", "counted": "no", "reason": "cost side"}],
        "single_product_flag": None,
        "durability_years_estimate": "10-20",
        "narrative": "Observed facts only.",
        "evidence_confidence": confidence,
        "evidence_note": None,
        "forward_threats": {
            "threat_level": "Low",
            "threats": [
                {
                    "name": f"threat {i}",
                    "level": level,
                    "level_test": f"{level}: gap 38%",
                    "what_could_happen": "Share falls.",
                    "observed_so_far": "Share 31%.",
                    "tripwire": {"metric": "share", "value_now": "31%", "review_level": "below 27.9% (90% of latest)"},
                }
                for i, level in enumerate(threat_levels)
            ],
        },
        "would_lower": "Share below 27.9%.",
        "would_raise": "Independent proof of retention.",
        "sources": [{"url": "https://example.com/a", "date": "2026-06-01", "claim": "share 31%"}],
    }


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def problems_of(record, ticker="PM"):
    with pytest.raises(mc.MoatCheckValidationError) as excinfo:
        mc.validate_pass_record(record, ticker)
    return excinfo.value.problems


# --- structural validation -------------------------------------------------------------------------------------------------------


def test_a_valid_record_passes_and_is_not_mutated():
    record = make_record()
    before = copy.deepcopy(record)
    corrected = mc.validate_pass_record(record, "pm")
    assert record == before and corrected["ticker"] == "PM"


@pytest.mark.parametrize("key", ["tag", "independent_support", "rule_effects"])
def test_the_retired_keys_are_rejected_as_unexpected(key):
    record = make_record()
    record[key] = None
    assert any("unexpected key" in p and key in p for p in problems_of(record))


def test_a_missing_key_is_rejected():
    record = make_record()
    del record["proof_basis"]
    assert any("missing key" in p and "proof_basis" in p for p in problems_of(record))


def test_a_non_object_is_rejected():
    assert problems_of(["not", "a", "record"]) == ["record: must be an object"]


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r.update(suggested_rating="huge_moat"), "suggested_rating"),
        (lambda r: r.update(reading="great"), "reading"),
        (lambda r: r.update(proof_basis="vendor"), "proof_basis"),
        (lambda r: r.update(evidence_confidence="Certain"), "evidence_confidence"),
        (lambda r: r.update(durability_years_estimate="forever"), "durability_years_estimate"),
        (lambda r: r["sources_rating"].update(brand_monopoly="great"), "sources_rating.brand_monopoly"),
        (lambda r: r["forward_threats"].update(threat_level="Extreme"), "forward_threats.threat_level"),
        (lambda r: r["forward_threats"]["threats"][0].update(level="Severe"), "threats[0].level"),
        (lambda r: r["observed_damage"][0].update(counted="maybe"), "observed_damage[0].counted"),
        (lambda r: r.update(ladder_levels=[1, 4]), "ladder_levels"),
    ],
)
def test_an_unknown_enumeration_value_is_rejected(mutate, fragment):
    record = make_record()
    mutate(record)
    assert any(fragment in p for p in problems_of(record))


def test_a_wrong_criteria_version_is_rejected():
    record = make_record()
    record["criteria_version"] = "moat-criteria-v5.1"
    assert any("criteria_version" in p for p in problems_of(record))


@pytest.mark.parametrize("bad", ["12 October 2026", "2026-13-40", None, 20261012])
def test_an_unparseable_checked_date_is_rejected(bad):
    record = make_record()
    record["checked_date"] = bad
    assert any("checked_date" in p for p in problems_of(record))


def test_a_ticker_other_than_the_one_checked_is_rejected():
    assert any("ticker" in p for p in problems_of(make_record(ticker="MO")))


def test_a_rated_source_with_a_null_fact_is_rejected():
    record = make_record()
    record["source_facts"]["switching_costs"] = None
    assert any("switching_costs" in p and "cited fact" in p for p in problems_of(record))


def test_an_unproven_source_carrying_a_fact_is_rejected():
    record = make_record()
    record["source_facts"]["economies_of_scale"] = fact()
    assert any("economies_of_scale" in p and "unproven" in p for p in problems_of(record))


def test_an_incomplete_fact_is_rejected():
    record = make_record()
    del record["source_facts"]["brand_monopoly"]["date"]
    assert any("source_facts.brand_monopoly" in p and "missing key" in p for p in problems_of(record))


def test_an_incomplete_observed_damage_entry_is_rejected():
    record = make_record()
    del record["observed_damage"][0]["reason"]
    assert any("observed_damage[0]" in p and "reason" in p for p in problems_of(record))


def test_an_empty_observed_damage_list_is_allowed():
    record = make_record()
    record["observed_damage"] = []
    mc.validate_pass_record(record, "PM")


@pytest.mark.parametrize("field", ["metric", "value_now", "review_level"])
def test_an_incomplete_tripwire_is_rejected(field):
    record = make_record()
    del record["forward_threats"]["threats"][0]["tripwire"][field]
    assert any("tripwire" in p and field in p for p in problems_of(record))


def test_an_incomplete_threat_is_rejected():
    record = make_record()
    del record["forward_threats"]["threats"][0]["level_test"]
    assert any("threats[0]" in p and "level_test" in p for p in problems_of(record))


def test_every_problem_is_reported_not_just_the_first():
    record = make_record()
    record["reading"] = "great"
    record["checked_date"] = "nope"
    record["source_facts"]["switching_costs"] = None
    assert len(problems_of(record)) == 3


# --- derived values: corrected, never rejected -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "levels, stated, expected",
    [
        (("Moderate", "High", "Low"), "Low", "High"),
        (("Low", "Moderate"), "High", "Moderate"),
        (("Low",), "Moderate", "Low"),
        ((), "High", "Low"),
        (("High",), "High", "High"),
    ],
)
def test_the_overall_threat_level_is_derived_from_the_threats(levels, stated, expected):
    record = make_record(threat_levels=levels)
    record["forward_threats"]["threat_level"] = stated
    assert mc.validate_pass_record(record, "PM")["forward_threats"]["threat_level"] == expected


@pytest.mark.parametrize("stated", ["Low", "Medium", "High"])
def test_company_reported_only_proof_forces_confidence_to_low(stated):
    corrected = mc.validate_pass_record(make_record(confidence=stated, proof="company_reported_only"), "PM")
    assert corrected["evidence_confidence"] == "Low"


def test_independent_proof_keeps_the_stated_confidence():
    assert mc.validate_pass_record(make_record(confidence="High", proof="independent"), "PM")["evidence_confidence"] == "High"


def test_a_derived_correction_is_not_a_rejection_and_changes_nothing_else():
    record = make_record(confidence="High", proof="company_reported_only", threat_levels=("High",))
    record["forward_threats"]["threat_level"] = "Low"
    corrected = mc.validate_pass_record(record, "PM")
    corrected["forward_threats"]["threat_level"] = "Low"
    corrected["evidence_confidence"] = "High"
    assert corrected == record


# --- reconcile -------------------------------------------------------------------------------------------------------------------


def checked(**kwargs):
    return mc.validate_pass_record(make_record(**kwargs), kwargs.get("ticker", "PM"))


def test_matching_ratings_are_stable_with_pass_1_detail():
    p1 = checked(rating="wide_moat", confidence="High", threat_levels=("High",))
    p1["would_lower"] = "pass one text"
    p2 = checked(rating="wide_moat", confidence="Medium", threat_levels=("Low",))
    p2["would_lower"] = "pass two text"
    values = mc.reconcile(p1, p2)
    assert values["status"] == "stable" and values["rating"] == "wide_moat"
    assert values["pass1_rating"] == values["pass2_rating"] == "wide_moat"
    assert values["evidence_confidence"] == "Medium"  # the lower of the two
    assert values["threat_level"] == "High" and values["would_lower"] == "pass one text"
    assert json.loads(values["source_ratings_json"]) == p1["sources_rating"]
    assert json.loads(values["forward_threats_json"]) == p1["forward_threats"]
    assert values["criteria_version"] == mc.MOAT_CRITERIA_VERSION


def test_different_ratings_are_inconclusive_with_nothing_suggested():
    values = mc.reconcile(checked(rating="wide_moat", confidence="High"), checked(rating="narrow_moat", confidence="High"))
    assert values["status"] == "inconclusive" and values["rating"] is None
    assert (values["pass1_rating"], values["pass2_rating"]) == ("wide_moat", "narrow_moat")
    assert values["evidence_confidence"] == "Low"
    detail = ("threat_level", "source_ratings_json", "source_facts_json", "observed_damage_json", "forward_threats_json",
              "would_lower", "would_raise", "evidence_note")
    assert all(values[k] is None for k in detail)


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("independent", "independent", "independent"),
        ("company_reported_only", "independent", "company_reported_only"),
        ("independent", "company_reported_only", "company_reported_only"),
        ("company_reported_only", "company_reported_only", "company_reported_only"),
    ],
)
def test_proof_basis_is_company_only_if_either_pass_says_so(a, b, expected):
    assert mc.reconcile(checked(proof=a), checked(proof=b))["proof_basis"] == expected


@pytest.mark.parametrize(
    "a, b, expected",
    [("Low", "High", "Low"), ("High", "Medium", "Medium"), ("High", "High", "High"), ("Medium", "Medium", "Medium")],
)
def test_confidence_is_the_lower_of_the_two_passes(a, b, expected):
    assert mc.reconcile(checked(confidence=a), checked(confidence=b))["evidence_confidence"] == expected


# --- append (history) and latest -------------------------------------------------------------------------------------------------


def test_append_writes_one_row_with_both_validated_passes(session):
    row = mc.append_moat_check(session, "pm", make_record(), make_record(), now=T0).row
    assert row.id is not None and row.ticker == "PM" and row.checked_at == T0 and row.status == "stable"
    stored = json.loads(row.pass1_json)
    assert stored["forward_threats"]["threat_level"] == "Moderate" and "tag" not in stored


def test_the_stored_passes_carry_the_derived_values(session):
    record = make_record(confidence="High", proof="company_reported_only", threat_levels=("High",))
    record["forward_threats"]["threat_level"] = "Low"
    row = mc.append_moat_check(session, "PM", record, record, now=T0).row
    stored = json.loads(row.pass1_json)
    assert stored["evidence_confidence"] == "Low" and stored["forward_threats"]["threat_level"] == "High"
    assert row.evidence_confidence == "Low" and row.proof_basis == "company_reported_only" and row.threat_level == "High"


def test_a_rerun_appends_a_second_row_and_changes_nothing_already_stored(session):
    first = mc.append_moat_check(session, "PM", make_record(), make_record(), now=T0).row
    before = first.model_dump()
    second = mc.append_moat_check(
        session, "PM", make_record(rating="wide_moat"), make_record(rating="wide_moat"), now=datetime(2026, 10, 13, 9, 0)
    ).row
    rows = session.exec(select(MoatCheck).order_by(MoatCheck.id)).all()
    assert [r.id for r in rows] == [first.id, second.id]
    assert rows[0].model_dump() == before and rows[1].rating == "wide_moat"


def test_latest_is_the_newest_by_checked_at_then_id(session):
    assert mc.get_latest_moat_check(session, "PM") is None
    mc.append_moat_check(session, "PM", make_record(), make_record(), now=datetime(2026, 10, 14))
    mc.append_moat_check(session, "PM", make_record(rating="wide_moat"), make_record(rating="wide_moat"), now=datetime(2026, 10, 12))
    newest = mc.append_moat_check(session, "PM", make_record(rating="no_moat"), make_record(rating="no_moat"), now=datetime(2026, 10, 14)).row
    mc.append_moat_check(session, "MO", make_record(ticker="MO"), make_record(ticker="MO"), now=datetime(2026, 10, 20))
    latest = mc.get_latest_moat_check(session, "pm")
    assert latest.id == newest.id and latest.rating == "no_moat"  # the same instant: the higher id wins


def test_latest_is_none_for_a_ticker_never_checked(session):
    mc.append_moat_check(session, "MO", make_record(ticker="MO"), make_record(ticker="MO"), now=T0)
    assert mc.get_latest_moat_check(session, "PM") is None


def test_an_invalid_pass_writes_nothing(session):
    bad = make_record()
    bad["source_facts"]["switching_costs"] = None
    with pytest.raises(mc.MoatCheckValidationError):
        mc.append_moat_check(session, "PM", make_record(), bad, now=T0)
    assert session.exec(select(MoatCheck)).all() == []


def test_a_known_etf_is_refused_and_nothing_is_written(session):
    session.add(FundamentalsCache(ticker="SPY", statement_type="profile", period="latest", fetched_at=T0, raw_json='[{"isEtf": true}]'))
    session.commit()
    with pytest.raises(ValueError, match="ETF"):
        mc.append_moat_check(session, "SPY", make_record(ticker="SPY"), make_record(ticker="SPY"), now=T0)
    assert session.exec(select(MoatCheck)).all() == []


def test_a_check_touches_no_rating_and_no_score(session):
    session.add(TickerMoat(ticker="PM", moat="wide_moat", updated_at=T0))
    session.commit()
    moat_before = session.get(TickerMoat, "PM").model_dump()
    mc.append_moat_check(session, "PM", make_record(rating="no_moat"), make_record(rating="no_moat"), now=T0)
    assert session.get(TickerMoat, "PM").model_dump() == moat_before
    assert session.exec(select(TickerScore)).all() == []
    assert len(session.exec(select(TickerMoat)).all()) == 1


def test_an_unrated_ticker_stays_unrated_after_a_check(session):
    mc.append_moat_check(session, "PM", make_record(), make_record(), now=T0)
    assert session.get(TickerMoat, "PM") is None


def test_the_module_calls_no_score_recompute():
    source = open(mc.__file__).read()
    assert "compute_ticker_score" not in source and "set_ticker_moat" not in source and "fmp_client" not in source


# --- registry, merge, backup -----------------------------------------------------------------------------------------------------


def test_the_table_is_keep_in_the_registry_and_not_a_manual_data_table():
    from data import ticker_data_registry as reg

    entry = reg.REGISTRY["moatcheck"]
    assert entry.table_class is reg.TableClass.KEEP and entry.key_column == "ticker"
    assert MoatCheck not in reg.MANUAL_DATA_MODELS and "moatcheck" not in reg.MANUAL_DATA_LABELS
    assert all(e.name != "moatcheck" for e in reg.PROTECTING_TABLES + reg.WIPE_TABLES)


def test_the_merge_helper_renames_every_history_row_and_deletes_none(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(merge, "engine", engine)
    monkeypatch.setattr(merge, "LOG_PATH", tmp_path / "merge.log")
    with Session(engine) as s:
        for ticker, when in (("BRK.B", datetime(2026, 10, 1)), ("BRK.B", datetime(2026, 10, 2)), ("BRK-B", datetime(2026, 10, 3)),
                             ("BRK-B", datetime(2026, 10, 4))):
            s.add(
                MoatCheck(ticker=ticker, checked_at=when, criteria_version=mc.MOAT_CRITERIA_VERSION, status="stable", rating="narrow_moat",
                          pass1_rating="narrow_moat", pass2_rating="narrow_moat", evidence_confidence="Low", proof_basis="independent",
                          pass1_json="{}", pass2_json="{}")
            )
        s.commit()
        before = {r.id: r.checked_at for r in s.exec(select(MoatCheck)).all()}

    changes = merge.merge_duplicate_ticker_identities()

    assert len(changes) == 2 and all("rename" in c for c in changes)  # the two dot-form rows renamed; no delete action
    with Session(engine) as s:
        rows = s.exec(select(MoatCheck)).all()
    assert {r.id: r.checked_at for r in rows} == before and {r.ticker for r in rows} == {"BRK-B"}


def test_the_nightly_backup_carries_the_table_and_its_rows(tmp_path):
    import pipeline.backup_db as backup_db

    path = tmp_path / "fathom.db"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        mc.append_moat_check(s, "PM", make_record(), make_record(), now=T0)
    engine.dispose()
    result = backup_db.create_backup(db_path=path, backup_dir=tmp_path / "backups")
    restored = tmp_path / "restored.db"
    with gzip.open(result, "rb") as src, open(restored, "wb") as dst:
        dst.write(src.read())
    conn = sqlite3.connect(str(restored))
    assert conn.execute("SELECT ticker, status, rating FROM moatcheck").fetchall() == [("PM", "stable", "narrow_moat")]
    conn.close()


def test_the_table_has_no_tag_column_and_the_composite_index():
    from sqlalchemy import inspect

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    inspector = inspect(engine)
    assert "tag" not in {c["name"] for c in inspector.get_columns("moatcheck")}
    assert any(i["column_names"] == ["ticker", "checked_at"] for i in inspector.get_indexes("moatcheck"))


# --- warnings: empty prose and a run-date mismatch are reported, never refused ----------------------------------------------------


@pytest.mark.parametrize("field", ["narrative", "margins_note", "would_lower", "would_raise"])
@pytest.mark.parametrize("empty", ["", "   ", None])
def test_an_empty_prose_field_is_saved_as_given_with_a_warning(session, field, empty):
    record = make_record()
    record[field] = empty
    saved = mc.append_moat_check(session, "PM", record, make_record(), now=T0)
    assert saved.warnings == [f"pass 1: {field} is empty (saved as given)"]
    assert json.loads(saved.row.pass1_json)[field] == empty and session.exec(select(MoatCheck)).all() == [saved.row]


def test_an_empty_evidence_note_warns_but_a_null_one_does_not(session):
    blank, null = make_record(), make_record()
    blank["evidence_note"], null["evidence_note"] = "  ", None
    assert mc.append_moat_check(session, "PM", blank, null, now=T0).warnings == ["pass 1: evidence_note is empty (saved as given)"]


def test_a_pass_with_every_prose_field_empty_still_saves_and_names_each_warning(session):
    record = make_record()
    for name in mc.PROSE_FIELDS:
        record[name] = ""
    saved = mc.append_moat_check(session, "PM", make_record(), record, now=T0)
    assert [w.split(" is empty")[0] for w in saved.warnings] == [f"pass 2: {name}" for name in mc.PROSE_FIELDS]


@pytest.mark.parametrize("field", mc.PROSE_FIELDS)
def test_a_prose_field_of_the_wrong_type_is_still_rejected(field):
    record = make_record()
    record[field] = ["not", "text"]
    assert any(field in p and "text or null" in p for p in problems_of(record))


def test_complete_prose_gives_no_warnings(session):
    assert mc.append_moat_check(session, "PM", make_record(), make_record(), now=T0).warnings == []


def test_a_checked_date_other_than_the_run_date_is_a_warning_not_a_refusal(session):
    from datetime import date

    other = make_record()
    other["checked_date"] = "2026-10-11"
    saved = mc.append_moat_check(session, "PM", make_record(), other, now=T0, run_date=date(2026, 10, 12))
    assert saved.warnings == ["pass 2: checked_date 2026-10-11 differs from run date 2026-10-12"]
    assert saved.row.id is not None


def test_no_run_date_means_no_date_warning(session):
    other = make_record()
    other["checked_date"] = "2026-01-01"
    assert mc.append_moat_check(session, "PM", make_record(), other, now=T0).warnings == []
