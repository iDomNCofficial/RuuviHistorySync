"""Manual history synchronization button for each RuuviTag."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Register a button for the configured tag."""
    async_add_entities([RuuviSyncButton(hass.data[DOMAIN][entry.entry_id])])


class RuuviSyncButton(ButtonEntity):
    """Request an immediate BLE GATT history synchronization."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_now"
    _attr_icon = "mdi:sync"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = f"{manager.address}_history_manual_sync"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, manager.address)},
            "name": f"RuuviTag {manager.address}",
            "manufacturer": "Ruuvi",
        }

    async def async_press(self) -> None:
        """Start the existing sync without blocking a UI press for GATT I/O."""
        if self.manager._closing or self.manager._lock.locked():
            return
        self.hass.async_create_task(self.manager.sync())
