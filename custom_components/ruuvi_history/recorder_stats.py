"""Fill missing Recorder statistics without replacing existing live statistics.

This module intentionally runs on Recorder's own worker thread. Home Assistant
2026.10.4 has no public five-minute historical-statistics import API.
"""

from time import time
import logging

from sqlalchemy import select

from homeassistant.components.recorder.db_schema import (
    Statistics,
    StatisticsMeta,
    StatisticsShortTerm,
)
from homeassistant.helpers.recorder import session_scope

from .history import five_minute_buckets, hourly_from_five_minute, missing_buckets

SHORT_TERM_DAYS = 9
RECENT_FIVE_MINUTE_GUARD = 20 * 60
RECENT_HOURLY_GUARD = 2 * 3600
_LOGGER = logging.getLogger(__name__)


def fill_missing_statistics(instance, metric_rows, now=None):
    """Fill *absent* five-minute/hourly buckets for known HA sensor IDs.

    Never overwrite an existing bucket: live sensor readings are authoritative
    and an archive-only aggregate must not replace their statistics. For a
    missing hourly bucket, build its mean from BOTH existing HA five-minute
    buckets and newly recovered ones, giving each time bucket equal weight.
    """
    now = time() if now is None else now
    counts = {"five_minute": 0, "hourly": 0, "errors": []}
    for entity_id, samples in metric_rows:
        try:
            result = _fill_one_metric(instance, entity_id, samples, now)
        except Exception as exc:
            message = f"{entity_id}: {type(exc).__name__}: {exc}"
            _LOGGER.exception("Ruuvi statistics import failed for %s", entity_id)
            counts["errors"].append(message)
            continue
        counts["five_minute"] += result[0]
        counts["hourly"] += result[1]
    return counts


def _fill_one_metric(instance, entity_id, samples, now):
    """Import one metric in its own transaction, independently of the rest."""
    buckets = five_minute_buckets(samples, now, SHORT_TERM_DAYS, RECENT_FIVE_MINUTE_GUARD)
    if not buckets:
        return (0, 0)

    earliest = now - SHORT_TERM_DAYS * 86400
    five_count = hourly_count = 0
    with session_scope(session=instance.get_session()) as session:
        meta_id = session.scalar(
            select(StatisticsMeta.id).where(StatisticsMeta.statistic_id == entity_id)
        )
        if meta_id is None:
            # Do not invent metadata for an entity that HA has never measured.
            return (0, 0)

        existing = session.execute(
            select(StatisticsShortTerm.start_ts, StatisticsShortTerm.mean,
                   StatisticsShortTerm.min, StatisticsShortTerm.max)
            .where(StatisticsShortTerm.metadata_id == meta_id)
            .where(StatisticsShortTerm.start_ts >= earliest - 3600)
        ).all()
        all_short = {
            int(stamp): (mean, min_value, max_value)
            for stamp, mean, min_value, max_value in existing
            if stamp is not None
        }
        for stamp, (mean, min_value, max_value) in sorted(
            missing_buckets(buckets, all_short).items()
        ):
            session.add(StatisticsShortTerm(
                metadata_id=meta_id, start_ts=float(stamp),
                mean=mean, min=min_value, max=max_value,
            ))
            all_short[stamp] = (mean, min_value, max_value)
            five_count += 1

        existing_hours = {int(value) for value in session.scalars(
            select(Statistics.start_ts)
            .where(Statistics.metadata_id == meta_id)
            .where(Statistics.start_ts >= earliest - 3600)
        ) if value is not None}
        relevant_hours = sorted({stamp - stamp % 3600 for stamp in buckets})
        for hour in relevant_hours:
            if hour in existing_hours or hour + 3600 > now - RECENT_HOURLY_GUARD:
                continue
            summary = hourly_from_five_minute(all_short, hour)
            if summary is None:
                continue
            session.add(Statistics(
                metadata_id=meta_id, start_ts=float(hour),
                mean=summary[0], min=summary[1], max=summary[2],
            ))
            hourly_count += 1

    return (five_count, hourly_count)
