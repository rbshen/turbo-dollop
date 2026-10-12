"""The advisory independent Moat check's persistence (docs/specs/moat-check.md; criteria docs/specs/moat-criteria.md, `moat-criteria-v5.2`).

Pure validation and reconciliation plus three session helpers. No network, no FMP, no engine of its own: every helper takes the caller's
`Session`. A check never touches TickerMoat, TickerScore or the Moat multiplier and never triggers a recompute: the only write in this module
is the INSERT of one `MoatCheck` row, and rows are never updated or deleted (history).

Validation is structural. It rejects missing or extra keys (so `tag`, `independent_support` and `rule_effects` are refused), unknown
enumeration values, a wrong criteria_version, an unparseable checked_date, a rated source with no fact, an unproven source that carries one,
and incomplete observed_damage / threat / tripwire fields. Empty prose (narrative, margins_note, would_lower, would_raise, evidence_note) is NOT
a refusal: it is saved as given and returned as a warning. Two values are DERIVED in code instead of rejected when they disagree with the
record: the overall `forward_threats.threat_level` (the highest level among the threats, Low when there are none) and `evidence_confidence`
(forced to Low when `proof_basis` is `company_reported_only`). The returned record carries the corrected values."""

import copy
import json
from datetime import date, datetime
from typing import Any, NamedTuple

from sqlmodel import Session, select

from core.models import MoatCheck
from core.tickers import normalize_ticker
from data.etf_data import is_known_etf

MOAT_CRITERIA_VERSION = "moat-criteria-v5.2"

RATINGS = ("no_moat", "narrow_moat", "wide_moat")
SOURCE_NAMES = ("brand_monopoly", "switching_costs", "barriers_to_entry", "network_effect", "economies_of_scale")
SOURCE_RATINGS = ("strong", "moderate", "weak", "absent", "unproven")
READINGS = ("supported", "neutral", "contradicted")
CONFIDENCES = ("Low", "Medium", "High")  # ordered: the index is the rank
PROOF_BASES = ("independent", "company_reported_only")
LEVELS = ("Low", "Moderate", "High")  # ordered: the index is the rank
DURABILITY = ("20+", "10-20", "<10")
STATUS_STABLE = "stable"
STATUS_INCONCLUSIVE = "inconclusive"

# The exact key set of a pass record (the criteria's Output section). No `tag`, `independent_support` or `rule_effects`.
RECORD_KEYS = frozenset(
    {
        "ticker", "criteria_version", "checked_date", "suggested_rating", "sources_rating", "source_facts", "moat_types",
        "realistic_competitors", "reading", "ladder_levels", "outcome_evidence", "outcome_supporting_item", "margins_note",
        "proof_basis", "observed_damage", "single_product_flag", "durability_years_estimate", "narrative", "evidence_confidence",
        "evidence_note", "forward_threats", "would_lower", "would_raise", "sources",
    }
)
# Free-text fields a research run can leave empty. An empty one is saved as given and reported as a warning, never a refusal: a full
# research run is not thrown away over empty prose. (Empty = null or whitespace-only; evidence_note is null by design when there is
# nothing to note, so a null evidence_note raises no warning.)
PROSE_FIELDS = ("narrative", "margins_note", "would_lower", "would_raise", "evidence_note")
_FACT_KEYS = frozenset({"fact", "source", "date"})
_EVIDENCE_KEYS = frozenset({"level", "item", "source", "date", "stale"})
_DAMAGE_KEYS = frozenset({"metric", "change", "period", "counted", "reason"})
_THREAT_KEYS = frozenset({"name", "level", "level_test", "what_could_happen", "observed_so_far", "tripwire"})
_TRIPWIRE_KEYS = frozenset({"metric", "value_now", "review_level"})
_SOURCE_KEYS = frozenset({"url", "date", "claim"})


class MoatCheckValidationError(ValueError):
    """A pass record failed structural validation; `problems` lists every problem found (not just the first)."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _check_keys(obj: Any, expected: frozenset, where: str, problems: list[str]) -> bool:
    """True when `obj` is a dict with exactly the expected keys; otherwise records what is missing or unexpected."""
    if not isinstance(obj, dict):
        problems.append(f"{where}: must be an object")
        return False
    missing, extra = sorted(expected - obj.keys()), sorted(obj.keys() - expected)
    if missing:
        problems.append(f"{where}: missing key(s) {', '.join(missing)}")
    if extra:
        problems.append(f"{where}: unexpected key(s) {', '.join(extra)}")
    return not missing and not extra


def _check_choice(value: Any, choices: tuple, where: str, problems: list[str]) -> None:
    if value not in choices:
        problems.append(f"{where}: {value!r} is not one of {', '.join(map(str, choices))}")


def _check_text_fields(obj: dict, names, where: str, problems: list[str]) -> None:
    for name in names:
        if not _is_text(obj.get(name)):
            problems.append(f"{where}.{name}: must be a non-empty string")


def _check_list_of_text(value: Any, where: str, problems: list[str]) -> None:
    if not isinstance(value, list) or not all(_is_text(v) for v in value):
        problems.append(f"{where}: must be a list of non-empty strings")


def _validate_sources(record: dict, problems: list[str]) -> None:
    ratings, facts = record["sources_rating"], record["source_facts"]
    names = frozenset(SOURCE_NAMES)
    ratings_ok = _check_keys(ratings, names, "sources_rating", problems)
    facts_ok = _check_keys(facts, names, "source_facts", problems)
    if ratings_ok:
        for name in SOURCE_NAMES:
            _check_choice(ratings[name], SOURCE_RATINGS, f"sources_rating.{name}", problems)
    if facts_ok:
        for name in SOURCE_NAMES:
            fact = facts[name]
            if fact is not None and _check_keys(fact, _FACT_KEYS, f"source_facts.{name}", problems):
                _check_text_fields(fact, _FACT_KEYS, f"source_facts.{name}", problems)
    if ratings_ok and facts_ok:
        for name in SOURCE_NAMES:
            rating, fact = ratings[name], facts[name]
            if rating == "unproven" and fact is not None:
                problems.append(f"source_facts.{name}: an unproven source must have a null fact")
            elif rating in SOURCE_RATINGS and rating != "unproven" and fact is None:
                problems.append(f"source_facts.{name}: a source rated {rating!r} must carry a cited fact (a source with no fact is unproven)")


def _validate_outcome(record: dict, problems: list[str]) -> None:
    _check_choice(record["reading"], READINGS, "reading", problems)
    levels = record["ladder_levels"]
    if not isinstance(levels, list) or not all(isinstance(v, int) and not isinstance(v, bool) and v in (1, 2, 3) for v in levels):
        problems.append("ladder_levels: must be a list of 1, 2 or 3")
    evidence = record["outcome_evidence"]
    if not isinstance(evidence, list):
        problems.append("outcome_evidence: must be a list")
    else:
        for i, item in enumerate(evidence):
            where = f"outcome_evidence[{i}]"
            if not _check_keys(item, _EVIDENCE_KEYS, where, problems):
                continue
            if isinstance(item["level"], bool) or item["level"] not in (1, 2, 3):
                problems.append(f"{where}.level: must be 1, 2 or 3")
            if not isinstance(item["stale"], bool):
                problems.append(f"{where}.stale: must be true or false")
            _check_text_fields(item, ("item", "source", "date"), where, problems)
    if record["outcome_supporting_item"] is not None and not _is_text(record["outcome_supporting_item"]):
        problems.append("outcome_supporting_item: must be null or a non-empty string")
    damage = record["observed_damage"]
    if not isinstance(damage, list):
        problems.append("observed_damage: must be a list")
    else:
        for i, entry in enumerate(damage):
            where = f"observed_damage[{i}]"
            if _check_keys(entry, _DAMAGE_KEYS, where, problems):
                _check_text_fields(entry, ("metric", "change", "period", "reason"), where, problems)
                _check_choice(entry["counted"], ("yes", "no"), f"{where}.counted", problems)


def _validate_threats(record: dict, problems: list[str]) -> None:
    block = record["forward_threats"]
    if not _check_keys(block, frozenset({"threat_level", "threats"}), "forward_threats", problems):
        return
    _check_choice(block["threat_level"], LEVELS, "forward_threats.threat_level", problems)
    threats = block["threats"]
    if not isinstance(threats, list):
        problems.append("forward_threats.threats: must be a list")
        return
    for i, threat in enumerate(threats):
        where = f"forward_threats.threats[{i}]"
        if not _check_keys(threat, _THREAT_KEYS, where, problems):
            continue
        _check_text_fields(threat, ("name", "level_test", "what_could_happen", "observed_so_far"), where, problems)
        _check_choice(threat["level"], LEVELS, f"{where}.level", problems)
        if _check_keys(threat["tripwire"], _TRIPWIRE_KEYS, f"{where}.tripwire", problems):
            _check_text_fields(threat["tripwire"], _TRIPWIRE_KEYS, f"{where}.tripwire", problems)


def validate_pass_record(record: Any, ticker: str) -> dict:
    """Validates one pass record against the criteria's output schema for `ticker` and returns a corrected deep copy.

    Raises MoatCheckValidationError (listing every problem) on a structural problem. The two derived values are corrected, never
    rejected: `forward_threats.threat_level` becomes the highest level among the threats (Low with none), and `evidence_confidence`
    becomes Low when `proof_basis` is `company_reported_only`."""
    problems: list[str] = []
    if not _check_keys(record, RECORD_KEYS, "record", problems):
        raise MoatCheckValidationError(problems)

    if normalize_ticker(str(record["ticker"])) != normalize_ticker(ticker):
        problems.append(f"ticker: {record['ticker']!r} does not match {ticker!r}")
    if record["criteria_version"] != MOAT_CRITERIA_VERSION:
        problems.append(f"criteria_version: {record['criteria_version']!r} is not {MOAT_CRITERIA_VERSION!r}")
    try:
        date.fromisoformat(record["checked_date"])
    except (TypeError, ValueError):
        problems.append(f"checked_date: {record['checked_date']!r} is not a YYYY-MM-DD date")
    _check_choice(record["suggested_rating"], RATINGS, "suggested_rating", problems)
    _validate_sources(record, problems)
    _check_list_of_text(record["moat_types"], "moat_types", problems)
    _check_list_of_text(record["realistic_competitors"], "realistic_competitors", problems)
    _validate_outcome(record, problems)
    _check_choice(record["proof_basis"], PROOF_BASES, "proof_basis", problems)
    if record["single_product_flag"] is not None and not _is_text(record["single_product_flag"]):
        problems.append("single_product_flag: must be null or a non-empty string")
    _check_choice(record["durability_years_estimate"], DURABILITY, "durability_years_estimate", problems)
    for name in PROSE_FIELDS:  # emptiness is a warning (prose_warnings), a wrong type is a structure problem
        if record[name] is not None and not isinstance(record[name], str):
            problems.append(f"{name}: must be text or null")
    _check_choice(record["evidence_confidence"], CONFIDENCES, "evidence_confidence", problems)
    _validate_threats(record, problems)
    sources = record["sources"]
    if not isinstance(sources, list):
        problems.append("sources: must be a list")
    else:
        for i, source in enumerate(sources):
            if _check_keys(source, _SOURCE_KEYS, f"sources[{i}]", problems):
                _check_text_fields(source, _SOURCE_KEYS, f"sources[{i}]", problems)
    if problems:
        raise MoatCheckValidationError(problems)

    corrected = copy.deepcopy(record)
    threats = corrected["forward_threats"]["threats"]
    corrected["forward_threats"]["threat_level"] = max((t["level"] for t in threats), key=LEVELS.index, default="Low")
    if corrected["proof_basis"] == "company_reported_only":
        corrected["evidence_confidence"] = "Low"
    return corrected


def prose_warnings(record: dict) -> list[str]:
    """Warnings for a validated record: each prose field that is empty (null or whitespace-only), except a null `evidence_note`."""
    warnings = []
    for name in PROSE_FIELDS:
        value = record[name]
        if value is None and name == "evidence_note":
            continue
        if value is None or not value.strip():
            warnings.append(f"{name} is empty (saved as given)")
    return warnings


def reconcile(pass1: dict, pass2: dict) -> dict:
    """Pure: the MoatCheck column values for two validated pass records (output of validate_pass_record).

    Same rating in both passes -> status `stable`, `rating` set and the detail columns are pass 1's. Different ratings -> status
    `inconclusive`, `rating` and the detail columns NULL, confidence Low. Confidence is otherwise the lower of the two passes, and
    `proof_basis` is `company_reported_only` if either pass says so."""
    stable = pass1["suggested_rating"] == pass2["suggested_rating"]
    confidence = "Low" if not stable else min(pass1["evidence_confidence"], pass2["evidence_confidence"], key=CONFIDENCES.index)
    values: dict[str, Any] = {
        "criteria_version": pass1["criteria_version"],
        "status": STATUS_STABLE if stable else STATUS_INCONCLUSIVE,
        "rating": pass1["suggested_rating"] if stable else None,
        "pass1_rating": pass1["suggested_rating"],
        "pass2_rating": pass2["suggested_rating"],
        "evidence_confidence": confidence,
        "proof_basis": "company_reported_only" if "company_reported_only" in (pass1["proof_basis"], pass2["proof_basis"]) else "independent",
        "threat_level": None,
        "source_ratings_json": None,
        "source_facts_json": None,
        "observed_damage_json": None,
        "forward_threats_json": None,
        "would_lower": None,
        "would_raise": None,
        "evidence_note": None,
    }
    if stable:
        values.update(
            threat_level=pass1["forward_threats"]["threat_level"],
            source_ratings_json=json.dumps(pass1["sources_rating"]),
            source_facts_json=json.dumps(pass1["source_facts"]),
            observed_damage_json=json.dumps(pass1["observed_damage"]),
            forward_threats_json=json.dumps(pass1["forward_threats"]),
            would_lower=pass1["would_lower"],
            would_raise=pass1["would_raise"],
            evidence_note=pass1["evidence_note"],
        )
    return values


class SavedMoatCheck(NamedTuple):
    """What append_moat_check returns: the inserted row and the warnings the save produced (empty prose fields, a pass whose
    checked_date differs from the run date). Warnings are reported to the caller and not stored."""

    row: MoatCheck
    warnings: list[str]


def append_moat_check(
    session: Session, ticker: str, pass1: Any, pass2: Any, now: datetime | None = None, run_date: date | None = None
) -> SavedMoatCheck:
    """Validates both passes, reconciles them and INSERTS one new row (history: an existing row is never touched). Raises
    MoatCheckValidationError (the problems of BOTH passes, each prefixed "pass 1:" / "pass 2:") when either record is invalid and ValueError for a known ETF/fund, writing nothing in either case.
    Empty prose fields and (when `run_date` is given) a pass whose checked_date differs from it are WARNINGS returned beside the
    row, never refusals. Never writes TickerMoat, never recomputes a score, never calls the network."""
    ticker = normalize_ticker(ticker)
    if is_known_etf(session, ticker):
        raise ValueError(f"{ticker} is an ETF or fund; an Economic Moat check does not apply to it")
    checked, problems = [], []
    for number, record in enumerate((pass1, pass2), start=1):  # both passes are checked, so one retry can fix every failing pass
        try:
            checked.append(validate_pass_record(record, ticker))
        except MoatCheckValidationError as exc:
            problems += [f"pass {number}: {problem}" for problem in exc.problems]
    if problems:
        raise MoatCheckValidationError(problems)
    warnings = []
    for number, record in enumerate(checked, start=1):
        warnings += [f"pass {number}: {w}" for w in prose_warnings(record)]
        if run_date is not None and record["checked_date"] != run_date.isoformat():
            warnings.append(f"pass {number}: checked_date {record['checked_date']} differs from run date {run_date.isoformat()}")
    row = MoatCheck(
        ticker=ticker,
        checked_at=now or datetime.now(),
        pass1_json=json.dumps(checked[0]),
        pass2_json=json.dumps(checked[1]),
        **reconcile(*checked),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return SavedMoatCheck(row, warnings)


def get_latest_moat_check(session: Session, ticker: str) -> MoatCheck | None:
    """The newest check for the ticker (by checked_at, then id), or None when it has never been checked ("Not checked yet")."""
    statement = (
        select(MoatCheck)
        .where(MoatCheck.ticker == normalize_ticker(ticker))
        .order_by(MoatCheck.checked_at.desc(), MoatCheck.id.desc())
        .limit(1)
    )
    return session.exec(statement).first()


def moat_check_payload(row: MoatCheck) -> dict[str, Any]:
    """The API view of a stored row (core/schemas.py::MoatCheckOut fields): the query columns, the detail parsed from its JSON columns
    when the row is stable, pass 1's whole record always, and pass 2's too when the row is inconclusive. Pure; reads nothing."""

    def parsed(text: str | None) -> Any:
        return None if text is None else json.loads(text)

    inconclusive = row.status == STATUS_INCONCLUSIVE
    return {
        "ticker": row.ticker,
        "checked_at": row.checked_at,
        "criteria_version": row.criteria_version,
        "criteria_is_current": row.criteria_version == MOAT_CRITERIA_VERSION,
        "status": row.status,
        "rating": row.rating,
        "pass1_rating": row.pass1_rating,
        "pass2_rating": row.pass2_rating,
        "evidence_confidence": row.evidence_confidence,
        "proof_basis": row.proof_basis,
        "threat_level": row.threat_level,
        "sources_rating": parsed(row.source_ratings_json),
        "source_facts": parsed(row.source_facts_json),
        "observed_damage": parsed(row.observed_damage_json),
        "forward_threats": parsed(row.forward_threats_json),
        "would_lower": row.would_lower,
        "would_raise": row.would_raise,
        "evidence_note": row.evidence_note,
        "pass1": parsed(row.pass1_json),  # always: the outcome reading, evidence, narrative and sources live only in the record
        "pass2": parsed(row.pass2_json) if inconclusive else None,
    }
