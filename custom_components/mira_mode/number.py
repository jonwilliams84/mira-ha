"""Number platform for Mira Mode integration."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_DEVICE_NAME, DOMAIN, TEMP_MAX, TEMP_MIN, TEMP_STEP
from .coordinator import MiraModeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MiraModeCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_DEVICE_NAME, f"Mira {address}")
    async_add_entities([MiraModeTemperatureNumber(coordinator, entry, name, address)])


class MiraModeTemperatureNumber(CoordinatorEntity[MiraModeCoordinator], NumberEntity):
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = TEMP_MIN
    _attr_native_max_value = TEMP_MAX
    _attr_native_step = TEMP_STEP
    _attr_mode = NumberMode.SLIDER
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MiraModeCoordinator, entry: ConfigEntry,
        device_name: str, address: str,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{address}_temperature"
        self._attr_name = "Temperature"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=device_name,
            manufacturer="Mira (Kohler)",
            model="Mira Mode",
        )
        self._assumed_temp: float | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._assumed_temp = None
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        if self._assumed_temp is not None:
            return self._assumed_temp
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.outlet_1_target_temp

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    async def async_set_native_value(self, value: float) -> None:
        self._assumed_temp = value
        self.async_write_ha_state()
        await self.coordinator.async_set_temperature(value)
