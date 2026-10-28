"""Home Assistant entry lifecycle for RuuviTag History Sync."""

from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .manager import HistoryManager

PLATFORMS = ("sensor", "binary_sensor", "button")


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    manager = HistoryManager(hass, entry)
    await manager.load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager

    entry.async_on_unload(bluetooth.async_register_callback(
        hass,
        manager.handle_advertisement,
        {"address": manager.address, "connectable": False},
        bluetooth.BluetoothScanningMode.ACTIVE,
    ))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def refresh_presence(_now):
        manager.notify()

    entry.async_on_unload(async_track_time_interval(
        hass, refresh_presence, timedelta(seconds=30)
    ))
    manager.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    success = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if success:
        manager = hass.data[DOMAIN].pop(entry.entry_id)
        await manager.close()
        entry.async_unload()
    return success
