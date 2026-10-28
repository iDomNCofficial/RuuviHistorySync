"""Live RuuviTag measurements and synchronization diagnostics."""

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    manager = hass.data[DOMAIN][entry.entry_id]
    entity_registry = er.async_get(hass)
    history_count_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{manager.address}_history_point_count"
    )
    if history_count_entity_id:
        entity_registry.async_remove(history_count_entity_id)

    async_add_entities([
        LiveRuuviSensor(manager, "temperature", "°C", SensorDeviceClass.TEMPERATURE),
        LiveRuuviSensor(manager, "humidity", "%", SensorDeviceClass.HUMIDITY),
        LiveRuuviSensor(manager, "pressure", "Pa", SensorDeviceClass.ATMOSPHERIC_PRESSURE),
        LiveRuuviSensor(manager, "battery_voltage", "V", SensorDeviceClass.VOLTAGE),
        LiveRuuviSensor(manager, "acceleration_total", "m/s²", None),
        LiveRuuviSensor(manager, "acceleration_x", "m/s²", None),
        LiveRuuviSensor(manager, "acceleration_y", "m/s²", None),
        LiveRuuviSensor(manager, "acceleration_z", "m/s²", None),
        LiveRuuviSensor(manager, "movement_counter", None, None),
        LiveRuuviSensor(manager, "rssi", "dBm", None),
        HistoryStatusSensor(manager),
    ])


class BaseHistorySensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager):
        self.manager = manager
        self._attr_device_info = {
            "identifiers": {(DOMAIN, manager.address)},
            "name": f"RuuviTag {manager.address}",
            "manufacturer": "Ruuvi",
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self.manager.subscribe(self._refresh))

    @callback
    def _refresh(self):
        self.async_write_ha_state()


class HistoryStatusSensor(BaseHistorySensor):
    _attr_translation_key = "last_sync"
    _attr_icon = "mdi:bluetooth-transfer"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager):
        super().__init__(manager)
        self._attr_unique_id = f"{manager.address}_history_last_sync"

    @property
    def native_value(self):
        if not self.manager.last_sync:
            return None
        value = datetime.fromisoformat(self.manager.last_sync)
        return value if value.tzinfo is not None else None

    @property
    def extra_state_attributes(self):
        return {
            "last_error": self.manager.last_error,
            "last_changed_values": self.manager.changed,
            "recorder_pending": self.manager.recorder_pending,
            "recorder_last_error": self.manager.recorder_last_error,
            "recorder_last_finished": self.manager.recorder_last_finished,
            "recorder_imported_statistics": self.manager.recorder_counts,
        }


class LiveRuuviSensor(BaseHistorySensor):
    """Live BLE sensor; retained only while the tag is within radio range."""

    _attr_entity_category = None
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager, key, unit, device_class):
        super().__init__(manager)
        self._key = key
        self._attr_translation_key = key
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_unique_id = f"{manager.address}_live_{key}"
        if key.startswith("acceleration_"):
            self._attr_suggested_display_precision = 2

    @property
    def native_value(self):
        value = self.manager.live.get(self._key)
        if self._key.startswith("acceleration_") and isinstance(value, (int, float)):
            return round(value, 2)
        return value

    @property
    def available(self):
        return self.manager.live_available() and self._key in self.manager.live
