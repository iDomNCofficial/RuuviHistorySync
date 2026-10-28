"""Durable Ruuvi log helpers, independent from Home Assistant."""

from datetime import datetime, timezone

ARCHIVE_DAYS = 10


def trim_records(records: dict, now: datetime, days: int = ARCHIVE_DAYS) -> dict:
    """Keep the rolling download/backfill window, not a second lifetime DB."""
    earliest = int(now.astimezone(timezone.utc).timestamp()) - days * 86400
    latest = int(now.timestamp()) + 60
    result = {}
    for key, values in records.items():
        try:
            stamp = int(key)
        except (ValueError, TypeError):
            continue
        if earliest <= stamp <= latest and isinstance(values, dict) and values:
            result[str(stamp)] = values
    return result


def metric_samples(records: dict, metric: str) -> tuple[tuple[int, float], ...]:
    """Return ordered, valid values for a historical metric."""
    from math import isfinite

    items = []
    for key, data in records.items():
        value = data.get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        value = float(value)
        if not isfinite(value):
            continue
        # The GATT history library exposes unavailable uint16 values instead
        # of omitting them. Never import those sentinels into Recorder.
        if metric == "humidity" and not 0 <= value <= 100:
            continue
        if metric == "pressure" and value == 65535:
            continue
        items.append((int(key), value))
    return tuple(sorted(items))
