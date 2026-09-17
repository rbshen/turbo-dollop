"""Computes each external data source's Settings "Status" health, backing
GET /api/config/data-source-health. Read side of core/data_source_health.py
(the write side) -- deliberately NOT a live reachability ping, purely a
function of an enabled/kill-switch flag (FMP only) plus
DataSourceHealth.last_success_at.

Imports core.data_source_health as a module (not `from ... import engine`)
so this always reads through whichever engine object that module's own
`engine` attribute currently points to -- a plain `from` import would
capture the real engine at import time, missing tests/conftest.py's
session-scoped monkeypatch of `data_source_health.engine` entirely."""

from datetime import datetime, timedelta

from sqlmodel import Session

import core.data_source_health as data_source_health
from core.config import settings
from core.models import DataSourceHealth
from core.schemas import DataSourceHealthOut, DataSourceStatusOut

# First-pass judgment-call thresholds, mirroring core/cron_health.py's own
# _DAILY_HOURS/_WEEKLY_HOURS reasoning -- both FMP fundamentals and Yahoo
# trend-structure are nightly-cadence data sources, so a similar
# tolerance-for-one-missed-run window applies here.
_STALE_AFTER_HOURS = 36
_FAILING_AFTER_HOURS = 24 * 8


def _last_success_at(source: str) -> datetime | None:
    with Session(data_source_health.engine) as session:
        row = session.get(DataSourceHealth, source)
        return row.last_success_at if row else None


def _status_for(enabled: bool, last_success_at: datetime | None, now: datetime) -> str:
    if not enabled:
        return "disabled_or_failing"
    if last_success_at is None or (now - last_success_at) >= timedelta(hours=_FAILING_AFTER_HOURS):
        return "disabled_or_failing"
    if (now - last_success_at) >= timedelta(hours=_STALE_AFTER_HOURS):
        return "stale"
    return "healthy"


def get_data_source_health() -> DataSourceHealthOut:
    now = datetime.now()

    fmp_last_success = _last_success_at("fmp")
    yahoo_last_success = _last_success_at("yahoo")

    return DataSourceHealthOut(
        sources=[
            DataSourceStatusOut(
                source="fmp",
                enabled=settings.fmp_enabled,
                status=_status_for(settings.fmp_enabled, fmp_last_success, now),
                last_success_at=fmp_last_success,
            ),
            DataSourceStatusOut(
                source="yahoo",
                # No kill switch exists for Yahoo (see clients/yahoo_client.py's
                # own docstring) -- always "enabled", status is purely a
                # function of how recently it last actually succeeded.
                enabled=True,
                status=_status_for(True, yahoo_last_success, now),
                last_success_at=yahoo_last_success,
            ),
        ]
    )
