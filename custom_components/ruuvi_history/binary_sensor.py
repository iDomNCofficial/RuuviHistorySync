"""RuuviTag radio presence using Home Assistant's BLE advertisements."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RuuviConnectivitySensor(manager)])


class RuuviConnectivitySensor(BinarySensorEntity):
    """On when recently heard; not an assertion of a persistent GATT link."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_translation_key = "bluetooth_connection"
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{manager.address}_bluetooth_connected"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, manager.address)},
            "name": f"RuuviTag {manager.address}",
            "manufacturer": "Ruuvi",
        }

    @property
    def is_on(self) -> bool:
        return self.manager.live_available()

    async def async_added_to_hass(self):
        self.async_on_remove(self.manager.subscribe(self._refresh))

    @callback
    def _refresh(self):
        self.async_write_ha_state()
    _attr_has_entity_name = True
