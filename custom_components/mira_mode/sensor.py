"""Sensor platform for Mira Mode integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
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
    async_add_entities([MiraModeActualTempSensor(coordinator, entry, name, address)])


class MiraModeActualTempSensor(CoordinatorEntity[MiraModeCoordinator], SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:thermometer-water"

    def __init__(
        self, coordinator: MiraModeCoordinator, entry: ConfigEntry,
        device_name: str, address: str,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{address}_actual_temp"
        self._attr_name = "Water Temperature"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=device_name,
            manufacturer="Mira (Kohler)",
            model="Mira Mode",
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.outlet_1_actual_temp

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None
