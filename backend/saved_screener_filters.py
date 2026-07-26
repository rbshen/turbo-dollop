from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from models import SavedScreenerFilter


def list_saved_filters(session: Session) -> list[SavedScreenerFilter]:
    return list(session.exec(select(SavedScreenerFilter).order_by(SavedScreenerFilter.name)).all())


def get_saved_filter(session: Session, name: str) -> SavedScreenerFilter | None:
    return session.exec(select(SavedScreenerFilter).where(SavedScreenerFilter.name == name)).first()


def upsert_saved_filter(
    session: Session,
    *,
    name: str,
    universe: str,
    sort_field: str,
    sort_direction: str,
    filters_json: str,
) -> SavedScreenerFilter:
    now = datetime.now()
    values = {
        "name": name,
        "universe": universe,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
        "filters_json": filters_json,
        "created_at": now,
        "updated_at": now,
    }
    stmt = sqlite_insert(SavedScreenerFilter).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={
            "universe": universe,
            "sort_field": sort_field,
            "sort_direction": sort_direction,
            "filters_json": filters_json,
            "updated_at": now,
        },
    )
    session.execute(stmt)
    session.commit()
    return get_saved_filter(session, name)


def delete_saved_filter(session: Session, name: str) -> bool:
    row = get_saved_filter(session, name)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
