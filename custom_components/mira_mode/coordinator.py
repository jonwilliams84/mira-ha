"""DataUpdateCoordinator for Mira Mode integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from bleak.exc import BleakError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .mira_protocol import MiraDeviceState, MiraModeBLEDevice

_LOGGER = logging.getLogger(__name__)

_BLE_ERRORS = (BleakError, TimeoutError, Exception)


class MiraModeCoordinator(DataUpdateCoordinator[MiraDeviceState | None]):

    def __init__(self, hass: HomeAssistant, device: MiraModeBLEDevice, name: str) -> None:
        super().__init__(
            hass, _LOGGER,
            name=f"Mira Mode {name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.device = device
        self._consecutive_failures = 0
        self._max_failures = 3

    async def _async_update_data(self) -> MiraDeviceState | None:
        try:
            state = await self.device.get_device_state()
            if state is None:
                self._consecutive_failures += 1
                _LOGGER.warning(
                    "No response from %s (attempt %d/%d), returning last known state",
                    self.device.address, self._consecutive_failures, self._max_failures,
                )
                await self.device.disconnect()
                if self._consecutive_failures >= self._max_failures:
                    self._consecutive_failures = 0
                    raise UpdateFailed(
                        f"No response from {self.device.address} after {self._max_failures} attempts"
                    )
                return self.data
            self._consecutive_failures = 0
            return state
        except UpdateFailed:
            raise
        except _BLE_ERRORS as err:
            self._consecutive_failures += 1
            await self.device.disconnect()
            if self._consecutive_failures >= self._max_failures:
                _LOGGER.warning(
                    "Transport error from %s after %d consecutive failures, marking unavailable: %s",
                    self.device.address, self._consecutive_failures, err,
                )
                self._consecutive_failures = 0
                raise UpdateFailed(f"BLE error: {err}") from err
            _LOGGER.warning(
                "Transport error from %s (attempt %d/%d), returning last known state: %s",
                self.device.address, self._consecutive_failures, self._max_failures, err,
            )
            return self.data

    async def async_set_outlet(self, outlet: int, state: bool) -> None:
        try:
            await self.device.set_outlet(outlet, state)
        except (BleakError, TimeoutError, Exception) as err:
            _LOGGER.error("Failed to set outlet %d: %s", outlet, err)
            await self.device.disconnect()
            raise

    async def async_set_temperature(self, temperature: float) -> None:
        try:
            await self.device.set_temperature(temperature)
        except (BleakError, TimeoutError, Exception) as err:
            _LOGGER.error("Failed to set temperature: %s", err)
            await self.device.disconnect()
            raise

    async def async_activate_preset(self, preset: int) -> None:
        try:
            await self.device.activate_preset(preset)
        except (BleakError, TimeoutError, Exception) as err:
            _LOGGER.error("Failed to activate preset %d: %s", preset, err)
            await self.device.disconnect()
            raise
        await self.async_request_refresh()
