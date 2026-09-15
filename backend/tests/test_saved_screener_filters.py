from sqlmodel import Session, SQLModel, create_engine

from data.saved_screener_filters import get_saved_filter, upsert_saved_filter


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_country_round_trips_through_upsert_same_as_watchlist_id():
    engine = _fresh_engine()
    with Session(engine) as session:
        upsert_saved_filter(
            session,
            name="HK view",
            universe="all",
            sort_field="overall_score",
            sort_direction="desc",
            filters_json="{}",
            watchlist_id=None,
            country="HK",
        )

        row = get_saved_filter(session, "HK view")

    assert row is not None
    assert row.country == "HK"


def test_country_defaults_to_none_when_not_passed():
    # A saved view created before the Country filter existed (or one that
    # never touched it) -- None means "load as the US default" on the
    # frontend, not an error.
    engine = _fresh_engine()
    with Session(engine) as session:
        upsert_saved_filter(
            session,
            name="No country",
            universe="all",
            sort_field="overall_score",
            sort_direction="desc",
            filters_json="{}",
        )

        row = get_saved_filter(session, "No country")

    assert row is not None
    assert row.country is None


def test_country_updates_on_conflict_like_every_other_column():
    engine = _fresh_engine()
    with Session(engine) as session:
        upsert_saved_filter(
            session,
            name="View",
            universe="all",
            sort_field="overall_score",
            sort_direction="desc",
            filters_json="{}",
            country="US",
        )
        upsert_saved_filter(
            session,
            name="View",
            universe="all",
            sort_field="overall_score",
            sort_direction="desc",
            filters_json="{}",
            country="HK",
        )

        row = get_saved_filter(session, "View")

    assert row is not None
    assert row.country == "HK"
