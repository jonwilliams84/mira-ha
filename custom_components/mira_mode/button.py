"""Button platform for Mira Mode integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_DEVICE_NAME, DOMAIN, NUM_PRESETS
from .coordinator import MiraModeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MiraModeCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_DEVICE_NAME, f"Mira {address}")
    async_add_entities([
        MiraModePresetButton(coordinator, entry, name, address, preset=i)
        for i in range(1, NUM_PRESETS + 1)
    ])


class MiraModePresetButton(CoordinatorEntity[MiraModeCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MiraModeCoordinator, entry: ConfigEntry,
        device_name: str, address: str, preset: int,
    ) -> None:
        super().__init__(coordinator)
        self._preset = preset
        self._address = address
        self._attr_unique_id = f"{address}_preset_{preset}"
        self._attr_name = f"Preset {preset}"
        self._attr_icon = "mdi:shower-head"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=device_name,
            manufacturer="Mira (Kohler)",
            model="Mira Mode",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_activate_preset(self._preset)
