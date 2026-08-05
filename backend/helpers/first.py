def _first(data: dict | list) -> dict:
    """Normalize an FMP response that's expected to be a single-row list (or
    already a dict) down to that one row -- shared by every stepN_data.py/
    ratios_data.py/etc. FMP-shaping module. Guards with isinstance(data, dict)
    rather than `data or {}` on the non-list branch, so a malformed/
    unexpected non-dict payload (e.g. a raw string) can't slip through and
    blow up a later `.get(...)` call."""
    if isinstance(data, list):
        return data[0] if data else {}
    return data if isinstance(data, dict) else {}
