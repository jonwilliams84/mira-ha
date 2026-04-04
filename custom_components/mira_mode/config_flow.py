"""Config flow for Mira Mode integration.

Supports BLE discovery of Mira Mode devices and interactive pairing.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak.exc import BleakError

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import (
    CONF_CLIENT_ID,
    CONF_DEVICE_NAME,
    CONF_SLOT,
    DOMAIN,
    SERVICE_UUID,
)
from .mira_protocol import MiraModeBLEDevice

_LOGGER = logging.getLogger(__name__)


class MiraModeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mira Mode."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._address: str | None = None
        self._name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        _LOGGER.debug(
            "Discovered Mira device: %s (%s)",
            discovery_info.name,
            discovery_info.address,
        )

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._address = discovery_info.address
        self._name = discovery_info.name or f"Mira Mode {discovery_info.address}"

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm Bluetooth discovery and proceed to pairing."""
        if user_input is not None:
            return await self.async_step_pair()

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._name or "Unknown",
                "address": self._address or "Unknown",
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user-initiated config flow (manual setup)."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._name = (
                user_input.get(CONF_DEVICE_NAME)
                or f"Mira Mode {self._address}"
            )

            await self.async_set_unique_id(self._address)
            self._abort_if_unique_id_configured()

            return await self.async_step_pair()

        # Scan for available Mira Mode devices
        self._discovered_devices = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            uuids_lower = {u.lower() for u in info.service_uuids}
            if SERVICE_UUID.lower() in uuids_lower:
                if info.address not in self._discovered_devices:
                    self._discovered_devices[info.address] = info

        if self._discovered_devices:
            addresses = {
                addr: f"{info.name or 'Mira Mode'} ({addr})"
                for addr, info in self._discovered_devices.items()
            }

            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ADDRESS): vol.In(addresses),
                        vol.Optional(CONF_DEVICE_NAME): str,
                    }
                ),
            )

        # No devices discovered -- allow manual address entry
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_DEVICE_NAME): str,
                }
            ),
            description_placeholders={
                "no_devices": "No Mira devices found nearby. Enter the BLE address manually."
            },
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the pairing step.

        Instructs user to hold the outlet button, then attempts pairing.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # User has confirmed they held the button -- attempt pairing
            try:
                assert self._address is not None
                client_name = (self._name or "HomeAssistant")[:20]
                client_id, slot = await MiraModeBLEDevice.pair(
                    self.hass,
                    self._address,
                    client_name=client_name,
                )

                _LOGGER.info(
                    "Paired with %s: client_id=0x%08X, slot=%d",
                    self._address,
                    client_id,
                    slot,
                )

                return self.async_create_entry(
                    title=self._name or f"Mira {self._address}",
                    data={
                        CONF_ADDRESS: self._address,
                        CONF_CLIENT_ID: client_id,
                        CONF_SLOT: slot,
                        CONF_DEVICE_NAME: self._name,
                    },
                )

            except BleakError as err:
                _LOGGER.error("Pairing failed: %s", err)
                errors["base"] = "pairing_failed"
            except Exception:
                _LOGGER.exception("Unexpected error during pairing")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "name": self._name or "Mira",
                "address": self._address or "Unknown",
            },
        )
