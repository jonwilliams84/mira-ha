"""Debug service — GATT enumeration via the HA bluetooth proxy.

Registers ``mira_mode.debug_enumerate``: takes a BLE address, resolves
the BLEDevice through HA's bluetooth manager (which knows about ESPHome
BT proxies), connects via bleak-retry-connector, walks every service +
characteristic + descriptor, and returns the structured tree as service
response_data. Also logs to the integration logger for visibility.

Use case: structural inspection of an unknown BLE device (e.g. a Mira
Activate) without having to release a new integration. Pair with an HCI
packet capture to figure out the runtime command protocol.

Call from Developer Tools → Services with::

    service: mira_mode.debug_enumerate
    data:
      address: "E5:B6:22:B1:DF:6D"
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_DEBUG_ENUMERATE = "debug_enumerate"

DEBUG_ENUMERATE_SCHEMA = vol.Schema(
    {
        vol.Required("address"): cv.string,
    }
)


def _bytes_summary(b: bytes) -> dict[str, Any]:
    """Hex + best-effort ASCII for a bytes value."""
    if not b:
        return {"hex": "", "ascii": None, "length": 0}
    hex_part = b.hex()
    ascii_part: str | None = None
    try:
        decoded = b.decode("utf-8")
        if all(32 <= ord(c) < 127 or c in "\r\n\t" for c in decoded):
            ascii_part = decoded
    except UnicodeDecodeError:
        pass
    return {"hex": hex_part, "ascii": ascii_part, "length": len(b)}


async def _enumerate(hass: HomeAssistant, address: str) -> dict[str, Any]:
    """Connect to *address* via HA's BT proxy and enumerate its GATT tree."""
    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise BleakError(
            f"Could not find BLE device {address}. Check the address and "
            f"that a connectable BT proxy is in range."
        )

    _LOGGER.info("debug_enumerate: connecting to %s via proxy", address)
    client = await establish_connection(
        BleakClient,
        ble_device,
        f"mira_mode_debug:{address}",
        max_attempts=3,
    )
    try:
        result: dict[str, Any] = {
            "address": address,
            "name": ble_device.name,
            "mtu": client.mtu_size,
            "services": [],
        }
        try:
            services = list(client.services)
        except Exception:
            services = list(await client.get_services())

        for svc in services:
            svc_dict: dict[str, Any] = {
                "uuid": svc.uuid,
                "handle": svc.handle,
                "characteristics": [],
            }
            for char in svc.characteristics:
                char_dict: dict[str, Any] = {
                    "uuid": char.uuid,
                    "handle": char.handle,
                    "properties": list(char.properties),
                    "descriptors": [],
                }
                if "read" in char.properties:
                    try:
                        val = await client.read_gatt_char(char.uuid)
                        char_dict["value"] = _bytes_summary(val)
                    except Exception as exc:
                        char_dict["read_error"] = str(exc)
                for desc in char.descriptors:
                    desc_dict: dict[str, Any] = {
                        "uuid": desc.uuid,
                        "handle": desc.handle,
                    }
                    try:
                        val = await client.read_gatt_descriptor(desc.handle)
                        desc_dict["value"] = _bytes_summary(val)
                    except Exception as exc:
                        desc_dict["read_error"] = str(exc)
                    char_dict["descriptors"].append(desc_dict)
                svc_dict["characteristics"].append(char_dict)
            result["services"].append(svc_dict)

        _LOGGER.info(
            "debug_enumerate: %s — %d service(s), MTU %d",
            address, len(result["services"]), result["mtu"]
        )
        return result
    finally:
        try:
            await client.disconnect()
        except Exception:
            _LOGGER.debug("disconnect failed", exc_info=True)


def async_register_debug_services(hass: HomeAssistant) -> None:
    """Register the debug services. Called once during integration setup."""
    if hass.services.has_service(DOMAIN, SERVICE_DEBUG_ENUMERATE):
        return

    async def handle_debug_enumerate(call: ServiceCall) -> dict[str, Any]:
        address = call.data["address"]
        try:
            return await _enumerate(hass, address)
        except Exception as exc:
            _LOGGER.error("debug_enumerate %s failed: %s", address, exc)
            return {"address": address, "error": str(exc)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_DEBUG_ENUMERATE,
        handle_debug_enumerate,
        schema=DEBUG_ENUMERATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
