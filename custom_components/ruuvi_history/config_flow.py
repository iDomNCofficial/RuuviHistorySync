"""Configuration of a RuuviTag for direct Bluetooth history reads."""

from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_ADDRESS, DOMAIN, RUUVI_MANUFACTURER_ID


def _ruuvi_address(discovery_info: BluetoothServiceInfoBleak) -> str | None:
    """Extract the stable MAC embedded in a Ruuvi data format 5 frame."""
    payload = discovery_info.manufacturer_data.get(RUUVI_MANUFACTURER_ID)
    if payload is None or len(payload) < 24 or payload[0] != 5:
        return None
    return ":".join(f"{part:02X}" for part in payload[18:24])


def _device_title(discovery_info: BluetoothServiceInfoBleak, address: str) -> str:
    """Return a useful title without depending on the adapter's BLE address."""
    if discovery_info.name and discovery_info.name.lower() != "unknown":
        return discovery_info.name
    return f"RuuviTag {address[-5:].replace(':', '')}"


class RuuviHistoryConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discover and configure RuuviTags that support direct GATT history."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_address: str | None = None
        self._discovery_title: str | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a RuuviTag found by Home Assistant Bluetooth discovery."""
        if not discovery_info.connectable:
            return self.async_abort(reason="not_connectable")
        address = _ruuvi_address(discovery_info)
        if address is None:
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._discovery_address = address
        self._discovery_title = _device_title(discovery_info, address)
        self.context["title_placeholders"] = {"name": self._discovery_title}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm a discovered RuuviTag."""
        assert self._discovery_address is not None
        assert self._discovery_title is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_title,
                data={CONF_ADDRESS: self._discovery_address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery_title},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List compatible RuuviTags currently visible to Home Assistant."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered_devices[address],
                data={CONF_ADDRESS: address},
            )

        await bluetooth.async_request_active_scan(self.hass)
        current_addresses = self._async_current_ids(include_ignore=False)
        for discovery_info in async_discovered_service_info(self.hass, True):
            address = _ruuvi_address(discovery_info)
            if (
                address is None
                or address in current_addresses
                or address in self._discovered_devices
            ):
                continue
            self._discovered_devices[address] = _device_title(
                discovery_info, address
            )

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered_devices)}
            ),
        )
