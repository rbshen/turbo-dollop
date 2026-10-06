"""Where the adjustable score weights live: one singleton row, a short in-process cache, and the save/reset writes
(scoring/weights.py is the pure definition: shape, defaults, bounds).

Reads NEVER write: an unseeded database simply serves DEFAULT_WEIGHTS at version 1 (what the seed row would hold), so a
read-only engine, a cron job and every test that never saved weights behave exactly as before. The row is created by the first
save, reset or GET of the settings endpoint (`get_score_weights_row`).

Caching follows core/data_groups.py: a 5 s in-process snapshot keyed on the engine, dropped by every write in this process. The
cron jobs and the recompute subprocess are separate processes that read the database directly (their own cache starts empty).
"""

import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.engine import Engine
from sqlmodel import Session

from core.models import ScoreWeightSettings
from scoring.weights import (
    DEFAULT_WEIGHTS,
    GROUPS,
    ScoreWeights,
    as_dict,
    weights_from_dict,
)

CONFIG_KEY = "default"
CACHE_TTL_SECONDS = 5.0
# The version an unseeded database reports: the version the lazy seed would write.
INITIAL_VERSION = 1


@dataclass(frozen=True)
class WeightsSnapshot:
    weights: ScoreWeights
    version: int
    updated_at: datetime | None  # None when no row exists yet


def _columns(weights: ScoreWeights) -> dict[str, int]:
    return {f"{group}_{field}": value for group in GROUPS for field, value in as_dict(getattr(weights, group)).items()}


def _snapshot_from_row(row: ScoreWeightSettings) -> WeightsSnapshot:
    nested: dict[str, dict[str, int]] = {group: {} for group in GROUPS}
    for group in GROUPS:
        for field in as_dict(getattr(DEFAULT_WEIGHTS, group)):
            nested[group][field] = getattr(row, f"{group}_{field}")
    return WeightsSnapshot(weights_from_dict(nested), row.weights_version, row.updated_at)


_cache: tuple[int, float, WeightsSnapshot] | None = None  # (id(engine), loaded_at, snapshot)


def invalidate_cache() -> None:
    global _cache
    _cache = None


def load_score_weights(bind: Engine) -> WeightsSnapshot:
    """The saved weights (or the defaults when nothing was ever saved), from the cache when it is under 5 s old. Read-only."""
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] == id(bind) and now - _cache[1] < CACHE_TTL_SECONDS:
        return _cache[2]
    with Session(bind) as session:
        row = session.get(ScoreWeightSettings, CONFIG_KEY)
    snapshot = _snapshot_from_row(row) if row is not None else WeightsSnapshot(DEFAULT_WEIGHTS, INITIAL_VERSION, None)
    _cache = (id(bind), now, snapshot)
    return snapshot


def get_score_weights_row(session: Session) -> ScoreWeightSettings:
    """Get-or-create (no migration tooling in this app, see MoatScoreConfig): the lazily seeded singleton row."""
    row = session.get(ScoreWeightSettings, CONFIG_KEY)
    if row is None:
        row = ScoreWeightSettings(
            key=CONFIG_KEY, weights_version=INITIAL_VERSION, updated_at=datetime.now(), **_columns(DEFAULT_WEIGHTS)
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        invalidate_cache()
    return row


def save_score_weights(session: Session, weights: ScoreWeights) -> ScoreWeightSettings:
    """Writes the set (already validated by the caller) and bumps weights_version by one."""
    row = get_score_weights_row(session)
    for column, value in _columns(weights).items():
        setattr(row, column, value)
    row.weights_version += 1
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    invalidate_cache()
    return row


def reset_score_weights(session: Session) -> ScoreWeightSettings:
    """Restores DEFAULT_WEIGHTS (a save like any other: the version still goes up)."""
    return save_score_weights(session, DEFAULT_WEIGHTS)


def snapshot_of(row: ScoreWeightSettings) -> WeightsSnapshot:
    return _snapshot_from_row(row)


def build_out(row: ScoreWeightSettings, recompute=None):
    """The GET /api/config/score-weights payload for a saved row (`recompute` is the latest RecomputeRunOut or None)."""
    from core.schemas import ScoreWeightsOut, WeightBoundsOut
    from scoring.overall import MOAT_WEIGHT
    from scoring.weights import BOUNDS, OVERALL_TOTAL, SUMS, weights_to_dict

    return ScoreWeightsOut(
        weights=weights_to_dict(snapshot_of(row).weights),
        defaults=weights_to_dict(DEFAULT_WEIGHTS),
        moat_weight=round(MOAT_WEIGHT * 100),
        overall_total=OVERALL_TOTAL,
        bounds={
            group: {field: WeightBoundsOut(min=low, max=high) for field, (low, high) in fields.items()}
            for group, fields in BOUNDS.items()
        },
        sums=dict(SUMS),
        weights_version=row.weights_version,
        updated_at=row.updated_at,
        recompute=recompute,
    )
