"""The Mira Mode integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, CONF_CLIENT_ID, CONF_SLOT, DOMAIN
from .coordinator import MiraModeCoordinator
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
    coordinator = MiraModeCoordinator(hass=hass, device=device, name=entry.title)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

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
