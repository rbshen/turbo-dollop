from sqlmodel import Session, SQLModel, create_engine

from data.saved_screener_filters import get_saved_filter, upsert_saved_filter


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _upsert(session, **overrides):
    values = dict(
        name="View",
        universe="all",
        sort_field="overall_score",
        sort_direction="desc",
        filters_json="{}",
        watchlist_id=None,
    )
    values.update(overrides)
    return upsert_saved_filter(session, **values)


def test_upsert_round_trips_a_saved_view():
    engine = _fresh_engine()
    with Session(engine) as session:
        _upsert(session, sort_field="step1_score")
        row = get_saved_filter(session, "View")

    assert row is not None
    assert row.sort_field == "step1_score"
    assert row.watchlist_id is None


def test_upsert_updates_on_conflict_by_name():
    engine = _fresh_engine()
    with Session(engine) as session:
        _upsert(session, sort_direction="desc")
        _upsert(session, sort_direction="asc")
        row = get_saved_filter(session, "View")

    assert row is not None
    assert row.sort_direction == "asc"
