"""The Mira Mode integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADDRESS,
    CONF_CLIENT_ID,
    CONF_SLOT,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .coordinator import MiraModeCoordinator
from .debug_service import async_register_debug_services
from .mira_protocol import MiraModeBLEDevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    client_id: int = entry.data[CONF_CLIENT_ID]
    slot: int = entry.data[CONF_SLOT]

    device = MiraModeBLEDevice(hass=hass, address=address, client_id=client_id, slot=slot)
    update_interval = entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)
    coordinator = MiraModeCoordinator(
        hass=hass, device=device, name=entry.title, update_interval=update_interval,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register on-demand debug services (idempotent — service-call only,
    # no background activity). Useful for diagnosing pairing/connection
    # issues and identifying Mira product variants by GATT tree.
    async_register_debug_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(device.disconnect)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: MiraModeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        try:
            await coordinator.device.disconnect()
        except Exception:
            _LOGGER.warning("Error disconnecting device during unload", exc_info=True)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change so the new poll interval applies."""
    await hass.config_entries.async_reload(entry.entry_id)
