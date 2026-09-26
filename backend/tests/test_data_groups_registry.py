"""Fails if any FMP endpoint or cached statement_type used in the code is not
mapped to a data group -- an unmapped one would bypass (endpoint) or ignore
(statement type) the per-group gate."""

import ast
import re
from pathlib import Path

import core.data_groups as dg

BACKEND = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {".venv", "tests", "node_modules", "scripts", "__pycache__"}


def _py_files():
    for p in BACKEND.rglob("*.py"):
        if not (set(p.relative_to(BACKEND).parts) & _SKIP_DIRS):
            yield p


def _endpoints_in_fmp_client() -> dict[str, list[str]]:
    """endpoint path -> list of FMPClient method names that call it."""
    src = (BACKEND / "clients" / "fmp_client.py").read_text()
    tree = ast.parse(src)
    out: dict[str, list[str]] = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FMPClient"]:
        for fn in [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)]:
            for call in ast.walk(fn):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "get"
                    and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    out.setdefault(call.args[0].value, []).append(fn.name)
    return out


def test_every_fmp_endpoint_is_mapped_to_a_known_group():
    endpoints = _endpoints_in_fmp_client()
    assert endpoints, "scan found no endpoints -- the scanner is broken"
    unmapped = sorted(e for e in endpoints if e not in dg.ENDPOINT_GROUP)
    assert not unmapped, f"unmapped FMP endpoints (add to core/data_groups.ENDPOINT_GROUP): {unmapped}"
    assert set(dg.ENDPOINT_GROUP.values()) <= set(dg.GROUPS)


def test_no_module_calls_fmp_get_with_a_literal_path_outside_the_client():
    offenders = []
    for p in _py_files():
        if p.name == "fmp_client.py":
            continue
        if re.search(r"fmp_client\.get\(\s*[\"']/", p.read_text()):
            offenders.append(str(p.relative_to(BACKEND)))
    assert not offenders, offenders


def test_mixed_group_endpoints_pass_an_explicit_group_override():
    """An endpoint reached by callers in different groups must say so at each
    call site; the documented overrides match the source."""
    src = (BACKEND / "clients" / "fmp_client.py").read_text()
    for endpoint, callers in dg.ENDPOINT_GROUP_OVERRIDES_USED.items():
        assert endpoint in dg.ENDPOINT_GROUP
        for method, group in callers.items():
            body = src[src.index(f"async def {method}(") :]
            body = body[: body.index("async def ", 10)] if "async def " in body[10:] else body
            default = dg.ENDPOINT_GROUP[endpoint]
            if group != default:
                assert f'group="{group}"' in body, f"{method} must pass group={group!r}"


def test_bulk_endpoints_are_ultimate_tier():
    for endpoint in dg.BULK_ENDPOINTS:
        assert endpoint in dg.ENDPOINT_GROUP
        assert dg.GROUPS[dg.ENDPOINT_GROUP[endpoint]].default_tier == "Ultimate"


def test_no_bulk_or_batch_endpoint_is_used_today():
    for e in _endpoints_in_fmp_client():
        assert "bulk" not in e and "batch" not in e, e


def _cache_statement_types() -> set[str]:
    types: set[str] = set()
    for p in _py_files():
        tree = ast.parse(p.read_text())
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = getattr(n.func, "id", getattr(n.func, "attr", ""))
            if name not in ("get_or_fetch", "get_or_fetch_earnings_aware", "force_fetch"):
                continue
            cands = [a for a in n.args[:3] if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            for k in n.keywords:
                if k.arg == "statement_type" and isinstance(k.value, ast.Constant):
                    cands = [k.value]
            # signature (session, ticker, statement_type, period, ...): the
            # statement type is the 3rd positional arg, but one caller passes
            # ("SPY", "price_change") in ticker/statement position -- take
            # whichever of the first three literals is a known cache key shape.
            if len(n.args) >= 3 and isinstance(n.args[2], ast.Constant):
                types.add(n.args[2].value)
    return types


def test_every_cached_statement_type_is_mapped():
    types = _cache_statement_types()
    assert "income_statement" in types, "scan found nothing -- the scanner is broken"
    unmapped = sorted(t for t in types if t not in dg.STATEMENT_TYPE_GROUP)
    assert not unmapped, f"unmapped statement types (add to STATEMENT_TYPE_GROUP): {unmapped}"
    assert set(dg.STATEMENT_TYPE_GROUP.values()) <= set(dg.GROUPS)


def test_group_metadata_is_complete():
    assert list(dg.GROUPS) == [
        "fundamentals", "profile_quote", "analyst_ratings", "segmentation", "news", "insider",
        "index_membership", "corporate_events", "daily_prices", "daily_prices_long", "intraday_bars", "extended_hours",
    ]
    for meta in dg.GROUPS.values():
        assert meta.default_tier in dg.TIERS


def test_p3_long_group_is_live_and_has_a_canary():
    long_ = dg.GROUPS["daily_prices_long"]
    assert long_.default_tier == "Premium"
    assert long_.live and long_.default_enabled
    for g in ("daily_prices", "daily_prices_long"):
        assert dg.PROBE_ENDPOINTS[g][0] == "/historical-price-eod/full"
    assert dg.PROBE_ENDPOINTS["daily_prices_long"][1]["symbol"] == "AAPL"
    assert "daily_prices_intl" not in dg.GROUPS and not hasattr(dg, "NON_US_CANARY_GROUPS")
    assert not any(hasattr(m, "falls_back") for m in dg.GROUPS.values())  # no group has a fallback provider


def test_every_live_group_has_a_probe_canary():
    live = {k for k, m in dg.GROUPS.items() if m.live}
    assert live <= set(dg.PROBE_ENDPOINTS)


def test_historical_price_eod_group_is_a_parameter_not_a_literal():
    src = (BACKEND / "clients" / "fmp_client.py").read_text()
    body = src[src.index("async def get_historical_price_eod(") :]
    body = body[: body.index("async def ", 10)]
    assert "group=group" in body and 'group: str = "daily_prices"' in body
