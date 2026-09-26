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
from core.data_groups import master_on
from core.models import DataSourceHealth
from core.schemas import DataSourceHealthOut, DataSourceStatusOut

# First-pass judgment-call thresholds, mirroring core/cron_health.py's own
# _DAILY_HOURS/_WEEKLY_HOURS reasoning -- FMP is a nightly-cadence data source, so a
# similar tolerance-for-one-missed-run window applies here.
_STALE_AFTER_HOURS = 36
_FAILING_AFTER_HOURS = 24 * 8


def _last_success_at(source: str) -> datetime | None:
    with Session(data_source_health.engine) as session:
        row = session.get(DataSourceHealth, source)
        return row.last_success_at if row else None


def _status_for(enabled: bool, last_success_at: datetime | None, now: datetime) -> str:
    if not enabled:
        return "disabled_or_failing"
    # No record yet is NOT evidence of failure -- most traffic is served
    # from a warm cache and never reaches the live FMPClient.get/
    # FMPClient.get choke point at all (see core/cache.py's
    # staleness-gated get_or_fetch), so a freshly-added DataSourceHealth
    # row (or a quiet period with nothing needing a live refetch) can
    # easily leave this None while the source is genuinely fine. Absent a
    # real reachability check, an enabled source with no history defaults
    # to healthy -- only an existing, aging timestamp downgrades the
    # status, never a missing one.
    if last_success_at is None:
        return "healthy"
    if (now - last_success_at) >= timedelta(hours=_FAILING_AFTER_HOURS):
        return "disabled_or_failing"
    if (now - last_success_at) >= timedelta(hours=_STALE_AFTER_HOURS):
        return "stale"
    return "healthy"


def get_data_source_health() -> DataSourceHealthOut:
    now = datetime.now()

    fmp_last_success = _last_success_at("fmp")

    return DataSourceHealthOut(
        sources=[
            DataSourceStatusOut(
                source="fmp",
                enabled=master_on(),
                status=_status_for(master_on(), fmp_last_success, now),
                last_success_at=fmp_last_success,
            ),
        ]
    )
