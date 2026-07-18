import asyncio

from sqlmodel import Session, SQLModel, create_engine

from cache import get_or_fetch


def test_concurrent_cache_miss_on_same_key_does_not_raise():
    """Regression test: two concurrent requests racing on the same
    (ticker, statement_type, period) cache key with no existing row used to
    raise sqlite3.IntegrityError on the second write (a plain INSERT), which
    propagated as an uncaught 500. Reproduces the real request pattern: two
    separate sessions (one per request, matching main.py's `with
    Session(engine)` per endpoint call), both missing the cache, both racing
    to write."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    call_count = {"n": 0}

    async def fetch_fn():
        call_count["n"] += 1
        # Yield control so both tasks can race past the initial SELECT
        # before either one writes -- without this, one call would simply
        # run to completion before the other starts.
        await asyncio.sleep(0.01)
        return {"value": call_count["n"]}

    async def run():
        with Session(engine) as session_a, Session(engine) as session_b:
            return await asyncio.gather(
                get_or_fetch(session_a, "TEST", "profile", "latest", fetch_fn, staleness_days=7),
                get_or_fetch(session_b, "TEST", "profile", "latest", fetch_fn, staleness_days=7),
            )

    results = asyncio.run(run())

    assert len(results) == 2
    assert call_count["n"] == 2  # both missed the cache and both fetched, as expected

    # A subsequent call should read back a single, consistent cached row.
    async def run_again():
        with Session(engine) as session:
            return await get_or_fetch(session, "TEST", "profile", "latest", fetch_fn, staleness_days=7)

    final = asyncio.run(run_again())
    assert final in results  # cache holds whichever write landed last, not a corrupted/duplicate state
    assert call_count["n"] == 2  # cache hit -- no third fetch
