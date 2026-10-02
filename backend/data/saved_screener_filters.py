from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.models import SavedScreenerFilter


# A saved view belongs to one screener: "stock" (the default, and every row saved before the ETF screener) or
# "etf". A name is unique per kind, so the two can share one.
DEFAULT_KIND = "stock"


def list_saved_filters(session: Session, kind: str = DEFAULT_KIND) -> list[SavedScreenerFilter]:
    return list(
        session.exec(
            select(SavedScreenerFilter).where(SavedScreenerFilter.kind == kind).order_by(SavedScreenerFilter.name)
        ).all()
    )


def get_saved_filter(session: Session, name: str, kind: str = DEFAULT_KIND) -> SavedScreenerFilter | None:
    return session.exec(
        select(SavedScreenerFilter).where(SavedScreenerFilter.name == name, SavedScreenerFilter.kind == kind)
    ).first()


def upsert_saved_filter(
    session: Session,
    *,
    name: str,
    universe: str,
    sort_field: str,
    sort_direction: str,
    filters_json: str,
    watchlist_id: int | None = None,
    kind: str = DEFAULT_KIND,
) -> SavedScreenerFilter:
    now = datetime.now()
    values = {
        "name": name,
        "kind": kind,
        "universe": universe,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
        "filters_json": filters_json,
        "watchlist_id": watchlist_id,
        "created_at": now,
        "updated_at": now,
    }
    stmt = sqlite_insert(SavedScreenerFilter).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["name", "kind"],
        set_={
            "universe": universe,
            "sort_field": sort_field,
            "sort_direction": sort_direction,
            "filters_json": filters_json,
            "watchlist_id": watchlist_id,
            "updated_at": now,
        },
    )
    session.execute(stmt)
    session.commit()
    return get_saved_filter(session, name, kind)


def delete_saved_filter(session: Session, name: str, kind: str = DEFAULT_KIND) -> bool:
    row = get_saved_filter(session, name, kind)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
