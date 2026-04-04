"""Switch platform for Mira Mode integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_DEVICE_NAME, DOMAIN
from .coordinator import MiraModeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MiraModeCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_DEVICE_NAME, f"Mira {address}")
    async_add_entities([
        MiraModeOutletSwitch(coordinator, entry, name, address, outlet=1),
        MiraModeOutletSwitch(coordinator, entry, name, address, outlet=2),
    ])


class MiraModeOutletSwitch(CoordinatorEntity[MiraModeCoordinator], SwitchEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True
    _attr_assumed_state = True

    def __init__(
        self, coordinator: MiraModeCoordinator, entry: ConfigEntry,
        device_name: str, address: str, outlet: int,
    ) -> None:
        super().__init__(coordinator)
        self._outlet = outlet
        self._address = address
        self._attr_unique_id = f"{address}_outlet_{outlet}"
        self._attr_name = f"Outlet {outlet}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=device_name,
            manufacturer="Mira (Kohler)",
            model="Mira Mode",
        )
        self._is_on: bool | None = self._state_from_coordinator()

    def _state_from_coordinator(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        if self._outlet == 1:
            return self.coordinator.data.outlet_1_running
        return self.coordinator.data.outlet_2_running

    @callback
    def _handle_coordinator_update(self) -> None:
        self._is_on = self._state_from_coordinator()
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_outlet(self._outlet, True)
        except Exception:
            _LOGGER.warning("Failed to turn on outlet %d, will correct on next poll", self._outlet)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_outlet(self._outlet, False)
        except Exception:
            _LOGGER.warning("Failed to turn off outlet %d, will correct on next poll", self._outlet)
