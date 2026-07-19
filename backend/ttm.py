def sum_last_four_quarters(quarters: list[dict], field: str) -> float | None:
    """Sum a flow-measure field across the 4 most recent quarters --
    trailing-twelve-months convention shared by Step 1 (income statement/
    cash flow TTM columns) and Step 5 (EBITDA, net interest expense, CFO).
    Returns None if fewer than 4 quarters have a non-null value for this
    field, rather than summing a partial year."""
    values = [q[field] for q in quarters if q.get(field) is not None]
    if len(values) < 4:
        return None
    return sum(values[:4])
