"""Experimental native Recorder state-history backfill for one RuuviTag.

Targeted at Home Assistant Core 2026.10.4. This uses internal Recorder ORM
models and its serialized task queue, NOT a supported public import API.
"""

from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass
import logging
from math import isfinite
from time import time

from sqlalchemy import delete, select, update

from homeassistant.components.recorder.db_schema import States
from homeassistant.components.recorder.tasks import RecorderTask
from homeassistant.helpers.recorder import session_scope

from .history import historical_samples_cover, missing_from_live_history
from .recorder_stats import fill_missing_statistics

_LOGGER = logging.getLogger(__name__)

MAX_HISTORY_AGE_SECONDS = 9 * 24 * 3600
LIVE_COLLISION_WINDOW_SECONDS = 60
HISTORY_INTERVAL_TOLERANCE_SECONDS = 30
RECENT_SAMPLE_GUARD_SECONDS = 120


@dataclass(slots=True)
class BackfillStatesTask(RecorderTask):
    """Insert genuinely missing metric states on Recorder's writing thread.

    No event is fired and the current state machine is not changed. Any
    existing live numeric measurements within one minute win. The task is
    idempotent: all existing numeric states are reread before every import.
    """

    state_rows: tuple[tuple[str, tuple[tuple[int, float], ...]], ...]
    metric_rows: tuple[tuple[str, tuple[tuple[int, float], ...]], ...] = ()
    on_finished: Callable | None = None
    history_interval_seconds: int = 300

    def run(self, instance) -> None:
        """Complete the queued task and report after Recorder's commit."""
        try:
            counts = self._run_import(instance)
        except Exception as exc:
            _LOGGER.exception("Ruuvi Recorder history import failed")
            if self.on_finished:
                instance.hass.add_job(self.on_finished, str(exc), None)
            raise
        else:
            if self.on_finished:
                metric_errors = counts.pop("errors", [])
                instance.hass.add_job(
                    self.on_finished,
                    "; ".join(metric_errors) if metric_errors else None,
                    counts,
                )

    def _run_import(self, instance):
        if not self.state_rows and not self.metric_rows:
            return {
                "states": 0,
                "unavailable_removed": 0,
                "five_minute": 0,
                "hourly": 0,
                "errors": [],
            }

        now = time()
        oldest = now - MAX_HISTORY_AGE_SECONDS
        newest = now - RECENT_SAMPLE_GUARD_SECONDS

        counts = {"states": 0, "unavailable_removed": 0, "errors": []}
        for entity_id, samples in self.state_rows:
            try:
                added, removed = self._backfill_entity(
                    instance, entity_id, samples, oldest, newest
                )
            except Exception as exc:
                message = f"{entity_id}: {type(exc).__name__}: {exc}"
                _LOGGER.exception(
                    "Ruuvi state-history import failed for %s", entity_id
                )
                counts["errors"].append(message)
                continue
            counts["states"] += added
            counts["unavailable_removed"] += removed

        statistic_counts = fill_missing_statistics(instance, self.metric_rows, now)
        counts["five_minute"] = statistic_counts["five_minute"]
        counts["hourly"] = statistic_counts["hourly"]
        counts["errors"].extend(statistic_counts["errors"])
        return counts

    def _backfill_entity(self, instance, entity_id, samples, oldest, newest):
        """Backfill one entity independently so another metric can still succeed."""
        if not entity_id or not samples:
            return (0, 0)

        deleted_state_ids = set()
        with session_scope(session=instance.get_session()) as session:
            metadata_id = instance.states_meta_manager.get(
                entity_id, session, True
            )
            if metadata_id is None:
                _LOGGER.warning("Ruuvi native backfill: unknown entity %s", entity_id)
                return (0, 0)

            # Keep all reads and inserts inside one transaction on the
            # serialized Recorder thread. Includes already-inserted rows.
            existing = session.execute(
                select(States.state_id, States.state, States.last_updated_ts, States.attributes_id)
                .where(States.metadata_id == metadata_id)
                .where(States.last_updated_ts >= oldest - LIVE_COLLISION_WINDOW_SECONDS)
                .where(States.last_updated_ts <= newest + LIVE_COLLISION_WINDOW_SECONDS)
                .order_by(States.last_updated_ts)
            ).all()
            live_times = []
            unavailable_rows = []
            attribute_id = None
            for state_id, value, stamp, attr_id in existing:
                if value == "unavailable" and stamp is not None:
                    unavailable_rows.append((int(state_id), float(stamp)))
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if stamp is None or not isfinite(numeric):
                    continue
                live_times.append(float(stamp))
                if attr_id is not None:
                    attribute_id = attr_id

            additions = []
            valid_sample_times = sorted(
                float(stamp) for stamp, value in samples
                if oldest <= stamp <= newest and isfinite(value)
            )
            for stamp, value in sorted(samples):
                if not oldest <= stamp <= newest or not isfinite(value):
                    continue
                if not missing_from_live_history(
                    stamp, live_times, LIVE_COLLISION_WINDOW_SECONDS
                ):
                    continue
                additions.append(
                    States(
                        metadata_id=metadata_id,
                        state=str(value),
                        last_updated_ts=float(stamp),
                        attributes_id=attribute_id,
                        origin_idx=0,
                    )
                )
                # Prevent duplicates inside a batch as well as across runs.
                live_times.insert(bisect_left(live_times, stamp), float(stamp))

            # Remove an unavailable marker only when consecutive archived
            # readings prove that the configured history cadence covers it.
            # Keep markers before, after, or inside a genuine archive gap.
            deleted_state_ids = {
                state_id for state_id, stamp in unavailable_rows
                if historical_samples_cover(
                    stamp,
                    valid_sample_times,
                    self.history_interval_seconds
                    + HISTORY_INTERVAL_TOLERANCE_SECONDS,
                )
            }
            if deleted_state_ids:
                # Core's purge performs the same unlink-before-delete sequence
                # to satisfy States.old_state_id's self-referencing FK.
                chunk_size = min(instance.max_bind_vars, 400)
                ids = sorted(deleted_state_ids)
                for offset in range(0, len(ids), chunk_size):
                    chunk = ids[offset:offset + chunk_size]
                    session.execute(
                        update(States)
                        .where(States.old_state_id.in_(chunk))
                        .values(old_state_id=None)
                    )
                    session.execute(delete(States).where(States.state_id.in_(chunk)))

            if additions:
                session.add_all(additions)
                _LOGGER.info(
                    "Ruuvi native history backfill: added %d states to %s",
                    len(additions), entity_id,
                )

            if deleted_state_ids:
                _LOGGER.info(
                    "Ruuvi native history backfill: removed %d unavailable states from %s",
                    len(deleted_state_ids), entity_id,
                )

        # Cache invalidation only after the transaction committed successfully.
        if deleted_state_ids:
            instance.states_manager.evict_purged_state_ids(deleted_state_ids)

        return (len(additions), len(deleted_state_ids))
