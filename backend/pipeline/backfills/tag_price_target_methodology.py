"""One-time, idempotent migration: tag existing PriceTargetSnapshot rows with
their `methodology` (see the column's comment in core/models.py).

  * fetched_at on 2026-09-16 -> 'legacy_all_analysts' (the all-analysts
    /price-target-news reconstruction backfill)
  * fetched_at on 2026-07-27 -> 'live_consensus' (the two manual AAPL/MSFT
    runs of the live job)

Only rows whose methodology IS NULL are touched, so it is safe to re-run and
never overwrites a tag. Rows written by the daily job are tagged at insert.

    uv run python -m pipeline.backfills.tag_price_target_methodology
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db import engine as default_engine, init_db

LEGACY_SQL = """
UPDATE pricetargetsnapshot SET methodology = 'legacy_all_analysts'
WHERE methodology IS NULL AND date(fetched_at) = '2026-09-16'
"""
LIVE_SQL = """
UPDATE pricetargetsnapshot SET methodology = 'live_consensus'
WHERE methodology IS NULL AND date(fetched_at) = '2026-07-27'
"""


def tag_methodology(engine: Engine) -> dict[str, int]:
    with engine.begin() as conn:
        legacy = conn.execute(text(LEGACY_SQL)).rowcount
        live = conn.execute(text(LIVE_SQL)).rowcount
    return {"legacy_all_analysts": legacy, "live_consensus": live}


if __name__ == "__main__":
    init_db()
    print(tag_methodology(default_engine))
