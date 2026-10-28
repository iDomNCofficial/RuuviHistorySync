"""Pure history normalization and Recorder backfill selection helpers."""

from collections import defaultdict
from bisect import bisect_left
from math import isfinite

from .const import METRICS


def missing_from_live_history(stamp: float, live_times: list[float], window: int = 60) -> bool:
    """Only use archived readings when no recorded value is nearby.

    ``live_times`` must be sorted. Recovered values already inserted by a
    prior import are also part of this list, making repeated jobs idempotent.
    """
    index = bisect_left(live_times, stamp)
    return all(
        abs(live_times[pos] - stamp) > window
        for pos in (index - 1, index)
        if 0 <= pos < len(live_times)
    )


def nearby_historical_sample(stamp: float, sample_times: list[float], window: int = 60) -> bool:
    """Whether an archived measurement can replace an unavailable marker."""
    index = bisect_left(sample_times, stamp)
    return any(
        abs(sample_times[pos] - stamp) <= window
        for pos in (index - 1, index)
        if 0 <= pos < len(sample_times)
    )


def historical_samples_cover(
    stamp: float, sample_times: list[float], max_gap: int
) -> bool:
    """Whether consecutive archived samples cover an unavailable marker.

    A marker is covered only when one archived measurement precedes it, one
    follows it, and the two samples are no farther apart than the configured
    history interval (plus the caller's clock-drift tolerance).
    """
    index = bisect_left(sample_times, stamp)
    if index == 0 or index >= len(sample_times):
        return False
    previous = sample_times[index - 1]
    following = sample_times[index]
    return previous <= stamp <= following and following - previous <= max_gap


def merge_entries(existing: dict, incoming: list[dict], now: int) -> tuple[dict, int]:
    """Merge Ruuvi's individually reported metrics by their original timestamp."""
    merged = {str(key): dict(value) for key, value in existing.items()}
    changed = 0
    for entry in incoming:
        try:
            stamp = int(entry["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        if stamp <= 0 or stamp > now + 60:
            continue
        values = merged.get(str(stamp), {}).copy()
        for metric in METRICS:
            value = entry.get(metric)
            if isinstance(value, (float, int)) and not isinstance(value, bool) and isfinite(value):
                if values.get(metric) != float(value):
                    values[metric] = float(value)
                    changed += 1
        if values:
            merged[str(stamp)] = values
    return merged, changed


def five_minute_buckets(samples, now, days=9, recent_guard=20 * 60):
    """Aggregate archive-only values into five-minute UTC buckets."""
    earliest = now - days * 86400
    latest = now - recent_guard
    groups = defaultdict(list)
    for stamp, value in samples:
        if earliest <= stamp <= latest and isfinite(value):
            groups[stamp - stamp % 300].append(float(value))
    return {
        key: (sum(values) / len(values), min(values), max(values))
        for key, values in groups.items()
    }


def missing_buckets(archived: dict, already_recorded: dict) -> dict:
    """HA's existing live five-minute statistics always take precedence."""
    return {stamp: row for stamp, row in archived.items() if stamp not in already_recorded}


def hourly_from_five_minute(buckets: dict, hour: int) -> tuple | None:
    """Average equal-duration five-minute buckets, regardless of source."""
    rows = [buckets.get(hour + offset) for offset in range(0, 3600, 300)]
    rows = [row for row in rows if row and all(value is not None for value in row)]
    if not rows:
        return None
    return (
        sum(row[0] for row in rows) / len(rows),
        min(row[1] for row in rows),
        max(row[2] for row in rows),
    )
