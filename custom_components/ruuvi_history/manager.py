"""Manage one RuuviTag's live Bluetooth stream and historical downloads."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance

from .archive import metric_samples, trim_records
from .backfill import BackfillStatesTask
from .const import CONF_ADDRESS, DOMAIN, HISTORY_INTERVAL_SECONDS, METRICS
from .history import merge_entries
from .live import decode_rawv2

_LOGGER = logging.getLogger(__name__)

LIVE_UNAVAILABLE_SECONDS = 180


class HistoryManager:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.address = entry.data[CONF_ADDRESS]
        self.store = Store(hass, 1, f"ruuvi_history_{entry.entry_id}")
        self.records = {}
        self.last_sync = None
        self.last_error = None
        self.changed = 0
        self._lock = asyncio.Lock()
        self._closing = False
        self.listeners = set()
        self.live = {}
        self.last_seen = None
        self.last_sequence = None
        self.recorder_pending = False
        self.recorder_last_error = None
        self.recorder_last_finished = None
        self.recorder_counts = None
        self._recorder_needs_retry = True
        self._recorder_last_attempt = 0.0
        self._sync_task = None
        # If the initial sync runs while the tag is away, its first subsequent
        # advertisement must trigger the missed catch-up.
        self._sync_on_next_seen = True

    def start(self):
        """Run an initial synchronization in the background."""
        self.hass.async_create_task(self.sync())

    def handle_advertisement(self, service_info, _change):
        """Consume HA's shared Bluetooth stream, no competing scanner."""
        payload = service_info.manufacturer_data.get(0x0499)
        if payload is None:
            return
        decoded = decode_rawv2(payload)
        if not decoded:
            return
        # Only accept this exact sensor's embedded MAC (DF5 bytes 18-23).
        encoded_mac = ":".join(f"{part:02X}" for part in payload[18:24])
        if encoded_mac != self.address:
            return
        sequence = int.from_bytes(payload[16:18], "big")
        rssi = service_info.rssi
        if isinstance(rssi, (int, float)) and not isinstance(rssi, bool):
            decoded["rssi"] = rssi
        # Record reception even when a repeat of the same measurement arrives.
        now = datetime.now(timezone.utc).timestamp()
        previous_last_seen = self.last_seen
        was_available = (
            previous_last_seen is not None
            and now - previous_last_seen < LIVE_UNAVAILABLE_SECONDS
        )
        self.last_seen = now

        # Synchronize once after a real absence. This also covers the first
        # advertisement after Home Assistant started while the tag was away.
        should_sync = self._sync_on_next_seen or (
            previous_last_seen is not None and not was_available
        )
        if should_sync and not self._lock.locked():
            self._sync_on_next_seen = False
            self.hass.async_create_task(self.sync())

        if sequence == self.last_sequence and decoded == self.live:
            return
        self.last_sequence = sequence
        # Replace, don't update: invalid/missing metrics must not remain stale.
        self.live = decoded
        self.notify()

    def live_available(self):
        """Do not report the last temperature as current during an absence."""
        return self.last_seen is not None and (
            datetime.now(timezone.utc).timestamp() - self.last_seen
            < LIVE_UNAVAILABLE_SECONDS
        )

    async def load(self):
        data = await self.store.async_load() or {}
        self.records = trim_records(data.get("records", {}), datetime.now(timezone.utc))
        self.last_sync = data.get("last_sync")

    async def close(self):
        self._closing = True
        if self._sync_task is not None:
            self._sync_task.cancel()
        async with self._lock:
            pass

    def subscribe(self, callback):
        self.listeners.add(callback)
        return lambda: self.listeners.discard(callback)

    def notify(self):
        for callback in tuple(self.listeners):
            callback()

    async def sync(self):
        if self._closing or self._lock.locked():
            return
        async with self._lock:
            self._sync_task = asyncio.current_task()
            try:
                # Import when needed, after HA has installed the integration requirement.
                from ruuvitag_sensor.ruuvi import RuuviTagSensor

                device = bluetooth.async_ble_device_from_address(self.hass, self.address)
                if device is None:
                    self._sync_on_next_seen = True
                    self.last_error = "Hors de portée Bluetooth"
                    return

                # One-hour overlap captures delayed/incomplete records after reconnect.
                stamp = max((int(t) for t in self.records), default=0)
                start = (
                    datetime.fromtimestamp(max(0, stamp - 3600), timezone.utc)
                    if stamp
                    else datetime.now(timezone.utc) - timedelta(days=10)
                )
                # Underlying library opens the BLE GATT connection directly.
                rows = await asyncio.wait_for(
                    RuuviTagSensor.download_history(
                        mac=self.address, start_time=start, device_type="ruuvitag"
                    ),
                    timeout=240,
                )
                now = datetime.now(timezone.utc)
                self._sync_on_next_seen = False
                self.records, self.changed = merge_entries(self.records, rows, int(now.timestamp()))
                self.records = trim_records(self.records, now)
                await self.store.async_save(
                    {"records": self.records, "last_sync": now.isoformat()}
                )
                self.last_sync = now.isoformat()
                if (
                    self.changed
                    or self._recorder_needs_retry
                    or now.timestamp() - self._recorder_last_attempt >= 1800
                ):
                    self._queue_native_history_backfill()
                self.last_error = None
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                _LOGGER.warning("RuuviTag %s: synchronization failed: %s", self.address, exc)
            finally:
                self._sync_task = None
                self.notify()

    def _queue_native_history_backfill(self):
        """Backfill the retained archive, tracking actual Recorder completion."""
        if self.recorder_pending:
            # New samples may have arrived while Recorder was still writing.
            self._recorder_needs_retry = True
            return
        registry = er.async_get(self.hass)
        metric_rows = []
        for metric in METRICS:
            metric_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{self.address}_live_{metric}"
            )
            if metric_id:
                samples = metric_samples(self.records, metric)
                if samples:
                    metric_rows.append((metric_id, samples))
        if not metric_rows:
            self.recorder_last_error = "Aucune entité de mesure disponible"
            return
        self.recorder_pending = True
        self._recorder_needs_retry = False
        try:
            get_instance(self.hass).queue_task(
                BackfillStatesTask(
                    state_rows=tuple(metric_rows),
                    metric_rows=tuple(metric_rows),
                    on_finished=self._recorder_completed,
                    history_interval_seconds=HISTORY_INTERVAL_SECONDS,
                )
            )
            self._recorder_last_attempt = datetime.now(timezone.utc).timestamp()
        except Exception:
            self.recorder_pending = False
            self._recorder_needs_retry = True
            raise

    @callback
    def _recorder_completed(self, error, counts):
        """Called on HA's event loop after Recorder has processed the task."""
        self.recorder_pending = False
        self.recorder_last_finished = datetime.now(timezone.utc).isoformat()
        self.recorder_last_error = error
        self.recorder_counts = counts
        self._recorder_needs_retry = self._recorder_needs_retry or error is not None
        self.notify()
