"""Clustering of currently-valid Liquidity Zone (LP) prices into support/
resistance zones. See engine.py's own module docstring for the full
reasoning behind the representative direction used for each side.
"""

from datetime import date, datetime
from typing import Literal

from .types import Zone

Representative = Literal["min", "max"]


def cluster_prices(items: list[tuple], cluster_pct: float, representative: Representative) -> list[Zone]:
    """`items` are (price, date) or (price, date, ts) tuples; the optional exact timestamp (intraday) rides
    along to Zone.formed_ts. Collapses adjacent items -- already sorted by price so that
    clustering only ever merges neighbors (descending for support,
    ascending for resistance, see engine.py) -- within cluster_pct% of a
    running cluster boundary into one Zone.

    representative="min": the zone's price is the LOWEST member of its
    cluster -- used for SUPPORT. A support zone is only genuinely broken
    once price sinks below its deepest member, so the lowest price is the
    conservative "last line of defense" and the one worth quoting.

    representative="max": the mirror, used for RESISTANCE -- the zone's
    price is the HIGHEST member of its cluster, since a resistance zone is
    only genuinely broken once price clears its highest member.

    Set cluster_pct<=0 to disable clustering entirely (every item becomes
    its own single-member zone). Worked example (cluster_pct=2.0,
    representative="min"): items (price desc) [(100, d1), (98, d2),
    (94, d3)] ->
      100 vs 98: (100-98)/100 = 2.0% <= 2.0% -> same zone, rep now 98/d2
      98 vs 94: (98-94)/98 = 4.1% > 2.0% -> new zone
      result: [Zone(98, 2, d2), Zone(94, 1, d3)]
    """
    if not items:
        return []
    items = [(it[0], it[1], it[2] if len(it) > 2 else None) for it in items]
    if cluster_pct <= 0:
        return [Zone(price=price, cluster_size=1, formed_at=d, formed_ts=ts) for price, d, ts in items]

    extreme = min if representative == "min" else max
    zones: list[Zone] = []
    rep_price, rep_date, rep_ts = items[0]
    cluster_size = 1

    for price, d, ts in items[1:]:
        pct_gap = abs(rep_price - price) / rep_price * 100.0
        if pct_gap <= cluster_pct:
            new_rep_price = extreme(rep_price, price)
            if new_rep_price != rep_price:
                rep_date, rep_ts = d, ts
            rep_price = new_rep_price
            cluster_size += 1
        else:
            zones.append(Zone(price=rep_price, cluster_size=cluster_size, formed_at=rep_date, formed_ts=rep_ts))
            rep_price, rep_date, rep_ts, cluster_size = price, d, ts, 1

    zones.append(Zone(price=rep_price, cluster_size=cluster_size, formed_at=rep_date, formed_ts=rep_ts))
    return zones
