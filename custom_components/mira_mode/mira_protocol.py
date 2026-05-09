"""BLE protocol implementation for Mira Mode digital showers.

Protocol reference: python-miramode (https://github.com/alexpilotti/python-miramode)
Protocol docs: https://github.com/nhannam/shower-controller-documentation

Frame format:
    [clientSlot, commandTypeId, payloadLength, payload..., CRC_high, CRC_low]

CRC-16/CCITT-FALSE is computed over:
    [clientSlot, commandTypeId, payloadLength, payload..., client_id (4 bytes BE)]
The client_id bytes are appended for CRC calculation ONLY -- they are NOT transmitted.

Pair command (0xEB) is special:
    - clientSlot = 0x00 (not yet assigned)
    - payload = new_client_id (4 bytes BE, randomly generated) + client_name (20 bytes NUL-padded)
    - CRC key = PAIR_MAGIC_ID instead of client_id
    - Total frame = 29 bytes, split into 20-byte BLE chunks for transmission

Notification (response) format:
    [clientSlot | 0x40, commandTypeId, payloadLength, payload...]

OperateOutlets (0x87) is the ONLY command for controlling outlets and temperature.
It always sends all state together:
    payload: [runningState, tempHigh, tempLow, outlet1FlowRate, outlet2FlowRate]

To avoid cross-contamination (e.g. changing temperature accidentally toggling outlets),
set_outlet() and set_temperature() both perform a fresh get_device_state() poll
immediately before sending OperateOutlets, so they always use the actual live state
rather than a potentially stale coordinator cache.
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
from dataclasses import dataclass
from typing import Any, Callable

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.core import HomeAssistant

from .const import (
    BLE_CHUNK_SIZE,
    CMD_DEVICE_STATE,
    CMD_OPERATE_OUTLETS,
    CMD_PAIR,
    CMD_PRESET,
    CMD_UNPAIR,
    COMMAND_TIMEOUT,
    CONNECT_TIMEOUT,
    CRC_INIT,
    CRC_POLY,
    FLOW_RATE_OFF,
    FLOW_RATE_ON,
    NOTIFY_CHAR_UUID,
    PAIR_MAGIC_ID,
    PAIR_TIMEOUT,
    RUNNING_STATE_RUNNING,
    RUNNING_STATE_STOPPED,
    TEMP_DEFAULT,
    WRITE_CHAR_UUID,
)

_LOGGER = logging.getLogger(__name__)

# Notification header length: [slot|0x40, cmdTypeId, payloadLength]
_NOTIFY_HEADER_LEN = 3
# Value in payload[0] that indicates pairing failure
_PAIR_FAILURE_BYTE = 0x80


@dataclass
class MiraDeviceState:
    """Represents the current state of a Mira Mode device."""

    outlet_1_running: bool = False
    outlet_2_running: bool = False
    outlet_1_target_temp: float = 38.0
    outlet_2_target_temp: float = 38.0
    outlet_1_actual_temp: float = 0.0
    outlet_2_actual_temp: float = 0.0
    # Raw flow rate bytes from the device (0x64=on, 0x00=off).
    outlet_1_flow_rate: int = FLOW_RATE_OFF
    outlet_2_flow_rate: int = FLOW_RATE_OFF


def crc16_ccitt(data: bytes) -> int:
    """Calculate CRC-16/CCITT-FALSE checksum.

    Polynomial: 0x1021, Initial value: 0xFFFF
    No final XOR. No input/output reflection. MSB-first.
    """
    crc = CRC_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ CRC_POLY
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def build_frame(
    client_slot: int,
    cmd: int,
    payload: bytes,
    client_id: int,
) -> bytes:
    """Build a standard command frame.

    Frame: [clientSlot, commandTypeId, payloadLength, payload..., CRC_high, CRC_low]
    CRC input: frame_bytes_without_crc + client_id (4 bytes BE)
    """
    pre_crc = bytearray([client_slot, cmd, len(payload)]) + bytearray(payload)
    crc_input = bytes(pre_crc) + struct.pack(">I", client_id)
    crc = crc16_ccitt(crc_input)
    return bytes(pre_crc) + struct.pack(">H", crc)


def build_pair_frame(new_client_id: int, client_name: str) -> bytes:
    """Build the pairing command frame (0xEB).

    Frame is 29 bytes:
        [0x00, 0xEB, 24, new_client_id (4B BE), client_name (20B NUL-padded), CRC (2B BE)]
    CRC key = PAIR_MAGIC_ID (not new_client_id).
    """
    name_bytes = client_name.encode("utf-8")[:20].ljust(20, b"\x00")
    payload = struct.pack(">I", new_client_id) + name_bytes  # 24 bytes

    pre_crc = bytearray([0x00, CMD_PAIR, 24]) + bytearray(payload)
    crc_input = bytes(pre_crc) + struct.pack(">I", PAIR_MAGIC_ID)
    crc = crc16_ccitt(crc_input)
    return bytes(pre_crc) + struct.pack(">H", crc)  # 29 bytes total


def parse_pair_response(data: bytes) -> int:
    """Parse a pair notification and return the assigned clientSlot.

    Notification: [clientSlot | 0x40, 0x01, payloadLength=1, assignedSlot]
    Raises ValueError on failure (payload[0] == 0x80) or malformed data.
    """
    if len(data) < _NOTIFY_HEADER_LEN + 1:
        raise ValueError(
            f"Pair response too short: {len(data)} bytes, data={data.hex()}"
        )

    assigned_slot = data[_NOTIFY_HEADER_LEN]
    if assigned_slot == _PAIR_FAILURE_BYTE:
        raise ValueError(
            "Device rejected pairing (response byte 0x80). "
            "Is the device in pairing mode?"
        )

    _LOGGER.debug("Parsed pair response: assigned clientSlot=%d", assigned_slot)
    return assigned_slot


def parse_device_state(data: bytes) -> MiraDeviceState:
    """Parse a device state notification.

    Notification: [slot|0x40, 0x01, payloadLength=10, payload...]
    DeviceState payload layout (from shower-controller-documentation):
        byte 0:   runningState (0=stopped, 1=running, 3=paused, 5=cold/min)
        bytes 1-2: targetTemperature (uint16 BE, tenths of C)
        bytes 3-4: actualTemperature (uint16 BE, tenths of C)
        byte 5:   outlet1FlowRate (0=off, 0x64=running)
        byte 6:   outlet2FlowRate (0=off, 0x64=running)
        bytes 7-8: secondsRemaining (uint16 BE)
        byte 9:   successfulUpdateCommandCounter

    NOTE: The device has a single shared temperature (not per-outlet).
    outlet_1/2_running is derived from the per-outlet flow rate bytes.
    outlet_1/2_target/actual_temp both reflect the single shared temperature.
    """
    if len(data) < _NOTIFY_HEADER_LEN + 10:
        raise ValueError(
            f"Device state response too short: {len(data)} bytes, data={data.hex()}"
        )

    payload = data[_NOTIFY_HEADER_LEN:]

    running_state = payload[0]
    target_temp = struct.unpack_from(">H", payload, 1)[0] / 10.0
    actual_temp = struct.unpack_from(">H", payload, 3)[0] / 10.0
    outlet1_flow = payload[5]
    outlet2_flow = payload[6]

    state = MiraDeviceState(
        outlet_1_running=outlet1_flow != 0,
        outlet_2_running=outlet2_flow != 0,
        outlet_1_target_temp=target_temp,
        outlet_2_target_temp=target_temp,
        outlet_1_actual_temp=actual_temp,
        outlet_2_actual_temp=actual_temp,
        outlet_1_flow_rate=outlet1_flow,
        outlet_2_flow_rate=outlet2_flow,
    )

    _LOGGER.debug(
        "Parsed device state: running=%d target=%.1fC actual=%.1fC o1_flow=%d o2_flow=%d",
        running_state,
        target_temp,
        actual_temp,
        outlet1_flow,
        outlet2_flow,
    )
    return state


class MiraModeBLEDevice:
    """Manages BLE communication with a Mira Mode device."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        client_id: int,
        slot: int,
    ) -> None:
        """Initialize the BLE device."""
        self._hass = hass
        self._address = address
        self._client_id = client_id
        self._slot = slot

        self._client: BleakClient | None = None
        self._connected = False
        self._response_event = asyncio.Event()
        self._response_data: bytes | None = None
        self._lock = asyncio.Lock()
        self._disconnect_callbacks: list[Callable[[], None]] = []
        self._filter_payload_len: int | None = None

    @property
    def address(self) -> str:
        return self._address

    @property
    def connected(self) -> bool:
        return self._connected and self._client is not None and self._client.is_connected

    def _notification_handler(self, _sender: Any, data: bytearray) -> None:
        """Handle incoming BLE notifications."""
        data_bytes = bytes(data)
        _LOGGER.debug("Notification from %s: %s", self._address, data_bytes.hex())
        if (
            self._filter_payload_len is not None
            and (
                len(data_bytes) < _NOTIFY_HEADER_LEN
                or data_bytes[2] != self._filter_payload_len
            )
        ):
            _LOGGER.debug(
                "Discarding notification payloadLen=%s (expected %d): %s",
                data_bytes[2] if len(data_bytes) > 2 else "?",
                self._filter_payload_len,
                data_bytes.hex(),
            )
            return
        self._response_data = data_bytes
        self._response_event.set()

    def _on_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.info("Mira device %s disconnected", self._address)
        self._connected = False
        for callback in self._disconnect_callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.exception("Error in disconnect callback")

    def register_disconnect_callback(self, callback: Callable[[], None]) -> None:
        self._disconnect_callbacks.append(callback)

    async def connect(self) -> None:
        if self.connected:
            return
        async with self._lock:
            if self.connected:
                return
            _LOGGER.debug("Connecting to Mira device %s", self._address)
            ble_device = async_ble_device_from_address(
                self._hass, self._address, connectable=True
            )
            if ble_device is None:
                raise BleakError(f"Could not find Mira device {self._address}")
            self._client = await establish_connection(
                BleakClient,
                ble_device,
                self._address,
                disconnected_callback=self._on_disconnect,
                timeout=CONNECT_TIMEOUT,
            )
            await self._client.start_notify(NOTIFY_CHAR_UUID, self._notification_handler)
            self._connected = True
            _LOGGER.info("Connected to Mira device %s", self._address)

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except BleakError:
                _LOGGER.debug("Error disconnecting from %s", self._address)
            finally:
                self._connected = False
                self._client = None

    async def _send_command(
        self,
        cmd: int,
        payload: bytes = b"",
        expect_response: bool = True,
    ) -> bytes | None:
        await self.connect()
        if self._client is None or not self._client.is_connected:
            raise BleakError("Not connected to device")
        frame = build_frame(self._slot, cmd, payload, self._client_id)
        _LOGGER.debug("Sending cmd 0x%02X to %s: %s", cmd, self._address, frame.hex())
        self._response_event.clear()
        self._response_data = None
        try:
            ble_response = expect_response
            await self._client.write_gatt_char(WRITE_CHAR_UUID, frame, response=ble_response)
        except (BleakError, TimeoutError, OSError, asyncio.TimeoutError) as exc:
            self._connected = False
            self._client = None
            if not isinstance(exc, BleakError):
                raise BleakError(str(exc)) from exc
            raise
        if not expect_response:
            return None
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout waiting for response to cmd 0x%02X from %s", cmd, self._address
            )
            return None
        return self._response_data

    async def get_device_state(self) -> MiraDeviceState | None:
        self._filter_payload_len = 10
        try:
            response = await self._send_command(CMD_DEVICE_STATE)
        finally:
            self._filter_payload_len = None
        if response is None:
            return None
        try:
            return parse_device_state(response)
        except (ValueError, struct.error) as err:
            _LOGGER.error(
                "Failed to parse device state from %s: %s (data=%s)",
                self._address, err, response.hex(),
            )
            return None

    def _build_operate_outlets_payload(self, o1_flow: int, o2_flow: int, temp_raw: int) -> bytes:
        running_state = RUNNING_STATE_RUNNING if (o1_flow or o2_flow) else RUNNING_STATE_STOPPED
        return bytes([
            running_state,
            (temp_raw >> 8) & 0xFF,
            temp_raw & 0xFF,
            o1_flow,
            o2_flow,
        ])

    async def set_outlet(self, outlet: int, state: bool) -> bool:
        fresh = await self.get_device_state()
        if fresh is not None:
            temp_raw = int(fresh.outlet_1_target_temp * 10)
            o1_flow = fresh.outlet_1_flow_rate
            o2_flow = fresh.outlet_2_flow_rate
        else:
            _LOGGER.warning(
                "Could not get fresh device state before set_outlet; "
                "using defaults (temp=%.1fC, both outlets off)", TEMP_DEFAULT,
            )
            temp_raw = int(TEMP_DEFAULT * 10)
            o1_flow = FLOW_RATE_OFF
            o2_flow = FLOW_RATE_OFF
        if outlet == 1:
            o1_flow = FLOW_RATE_ON if state else FLOW_RATE_OFF
        else:
            o2_flow = FLOW_RATE_ON if state else FLOW_RATE_OFF
        payload = self._build_operate_outlets_payload(o1_flow, o2_flow, temp_raw)
        _LOGGER.debug(
            "OperateOutlets (set_outlet): outlet=%d state=%s temp=%.1fC o1_flow=%d o2_flow=%d",
            outlet, "ON" if state else "OFF", temp_raw / 10.0, o1_flow, o2_flow,
        )
        await self._send_command(CMD_OPERATE_OUTLETS, payload, expect_response=False)
        return True

    async def set_temperature(self, temperature: float) -> bool:
        fresh = await self.get_device_state()
        if fresh is not None:
            o1_flow = fresh.outlet_1_flow_rate
            o2_flow = fresh.outlet_2_flow_rate
        else:
            _LOGGER.warning(
                "Could not get fresh device state before set_temperature; "
                "outlets will be set off"
            )
            o1_flow = FLOW_RATE_OFF
            o2_flow = FLOW_RATE_OFF
        temp_raw = int(temperature * 10)
        payload = self._build_operate_outlets_payload(o1_flow, o2_flow, temp_raw)
        _LOGGER.debug(
            "OperateOutlets (set_temperature): temp=%.1fC o1_flow=%d o2_flow=%d",
            temperature, o1_flow, o2_flow,
        )
        await self._send_command(CMD_OPERATE_OUTLETS, payload, expect_response=False)
        return True

    async def activate_preset(self, preset: int) -> bool:
        if preset < 1 or preset > 3:
            raise ValueError(f"Invalid preset number: {preset}")
        preset_slot = preset - 1
        _LOGGER.debug("Activating preset slot %d (preset #%d)", preset_slot, preset)
        response = await self._send_command(CMD_PRESET, bytes([preset_slot]))
        return response is not None

    @staticmethod
    async def pair(
        hass: HomeAssistant,
        address: str,
        client_name: str = "HomeAssistant",
    ) -> tuple[int, int]:
        _LOGGER.info("[PAIR] Starting pairing with %s (timeout=%ds)", address, int(PAIR_TIMEOUT))
        ble_device = async_ble_device_from_address(hass, address, connectable=True)
        if ble_device is None:
            raise BleakError(f"Could not find device {address}")
        new_client_id = struct.unpack(">I", os.urandom(4))[0]
        _LOGGER.debug("[PAIR] Generated new_client_id=0x%08X", new_client_id)
        frame = build_pair_frame(new_client_id, client_name)
        _LOGGER.debug("[PAIR] Pair frame (%d bytes): %s", len(frame), frame.hex())
        response_event = asyncio.Event()
        response_data: dict[str, bytes | None] = {"data": None}

        def notification_handler(_sender: Any, data: bytearray) -> None:
            _LOGGER.debug("[PAIR] Notification from %s: %s", address, bytes(data).hex())
            response_data["data"] = bytes(data)
            response_event.set()

        client = await establish_connection(
            BleakClient, ble_device, address, timeout=CONNECT_TIMEOUT,
        )
        _LOGGER.debug("[PAIR] Connected to %s", address)
        try:
            await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
            _LOGGER.debug("[PAIR] Subscribed to notifications")
            for i in range(0, len(frame), BLE_CHUNK_SIZE):
                chunk = frame[i : i + BLE_CHUNK_SIZE]
                _LOGGER.debug("[PAIR] Writing chunk [%d:%d]: %s", i, i + len(chunk), chunk.hex())
                await client.write_gatt_char(WRITE_CHAR_UUID, chunk, response=True)
            _LOGGER.info(
                "[PAIR] Pair command sent -- waiting up to %ds for device response...",
                int(PAIR_TIMEOUT),
            )
            try:
                await asyncio.wait_for(response_event.wait(), timeout=PAIR_TIMEOUT)
            except asyncio.TimeoutError as err:
                raise BleakError(
                    f"Timeout after {int(PAIR_TIMEOUT)}s waiting for pair response from {address}. "
                    "Is the device still in pairing mode? "
                    "(LED should be flashing -- hold outlet button 5 seconds to re-enter)"
                ) from err
            raw = response_data["data"]
            if raw is None:
                raise BleakError("No pair response received")
            _LOGGER.info("[PAIR] Response from %s: %s", address, raw.hex())
            assigned_slot = parse_pair_response(raw)
            _LOGGER.info(
                "[PAIR] Pairing successful: client_id=0x%08X, assigned slot=%d",
                new_client_id, assigned_slot,
            )
            return new_client_id, assigned_slot
        finally:
            _LOGGER.debug("[PAIR] Disconnecting from %s", address)
            try:
                await client.disconnect()
            except BleakError:
                pass
