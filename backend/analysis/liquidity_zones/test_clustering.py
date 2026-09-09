from datetime import date

from analysis.liquidity_zones.clustering import cluster_prices

D1, D2, D3 = date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)


def test_support_clustering_worked_example_from_the_reference_doc():
    # 100 vs 98: 2.0% <= 2.0% -> same zone, rep=98. 98 vs 94: 4.1% > 2.0% -> new zone.
    items = [(100.0, D1), (98.0, D2), (94.0, D3)]

    zones = cluster_prices(items, cluster_pct=2.0, representative="min")

    assert [z.price for z in zones] == [98.0, 94.0]
    assert [z.cluster_size for z in zones] == [2, 1]
    assert zones[0].formed_at == D2  # the lowest (representative) member's own date


def test_support_clustering_chains_multiple_members_into_one_zone():
    # 100 vs 99: 1.0% <= 3% -> extend, rep=99. 99 vs 97: 2.0% <= 3% -> extend, rep=97.
    items = [(100.0, D1), (99.0, D2), (97.0, D3)]

    zones = cluster_prices(items, cluster_pct=3.0, representative="min")

    assert [z.price for z in zones] == [97.0]
    assert zones[0].cluster_size == 3
    assert zones[0].formed_at == D3


def test_resistance_clustering_uses_the_highest_member_as_representative():
    # Ascending input (resistance walks low-to-high), representative=max.
    # 94 vs 96: (96-94)/94 = 2.1% <= 3% -> same zone, rep becomes max(94,96)=96.
    # 96 vs 100: (100-96)/96 = 4.2% > 3% -> new zone.
    items = [(94.0, D1), (96.0, D2), (100.0, D3)]

    zones = cluster_prices(items, cluster_pct=3.0, representative="max")

    assert [z.price for z in zones] == [96.0, 100.0]
    assert [z.cluster_size for z in zones] == [2, 1]
    assert zones[0].formed_at == D2  # the highest (representative) member's own date


def test_cluster_pct_zero_disables_clustering():
    items = [(100.0, D1), (98.0, D2), (94.0, D3)]

    zones = cluster_prices(items, cluster_pct=0, representative="min")

    assert [z.price for z in zones] == [100.0, 98.0, 94.0]
    assert all(z.cluster_size == 1 for z in zones)


def test_empty_input_returns_no_zones():
    assert cluster_prices([], cluster_pct=2.0, representative="min") == []
