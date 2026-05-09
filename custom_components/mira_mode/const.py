"""Constants for the Mira Mode integration."""

from __future__ import annotations

DOMAIN = "mira_mode"

# BLE UUIDs
SERVICE_UUID = "bccb0001-ca66-11e5-88a4-0002a5d5c51b"
WRITE_CHAR_UUID = "bccb0002-ca66-11e5-88a4-0002a5d5c51b"
NOTIFY_CHAR_UUID = "bccb0003-ca66-11e5-88a4-0002a5d5c51b"

# Command type IDs (commandTypeId byte in frame)
CMD_OPERATE_OUTLETS = 0x87  # payload: [runningState, tempHigh, tempLow, o1FlowRate, o2FlowRate]
CMD_DEVICE_STATE = 0x07     # payload: (none) -- request current state
CMD_PRESET = 0x09           # payload: presetSlot (0-indexed)
CMD_UNPAIR = 0x19           # payload: targetClientSlot
CMD_PAIR = 0xEB             # payload: new_client_id (4 bytes BE) + client_name (20 bytes)

# Magic ID used as CRC key during pairing (instead of real client_id)
PAIR_MAGIC_ID = 0x54D2EE63

# BLE MTU chunk size -- pair frame (29 bytes) must be split into 20-byte writes
BLE_CHUNK_SIZE = 20

# Outlet flow rate values
FLOW_RATE_ON = 0x64   # 100% -- any non-zero value turns the outlet on
FLOW_RATE_OFF = 0x00

# Running state values
RUNNING_STATE_STOPPED = 0x00
RUNNING_STATE_RUNNING = 0x01
RUNNING_STATE_PAUSED = 0x03

# Temperature limits (in degrees Celsius)
TEMP_MIN = 20.0
TEMP_MAX = 45.0
TEMP_STEP = 0.5
TEMP_DEFAULT = 38.0

# CRC-16/CCITT-FALSE parameters
CRC_POLY = 0x1021
CRC_INIT = 0xFFFF

# Config entry keys
CONF_CLIENT_ID = "client_id"
CONF_SLOT = "slot"
CONF_DEVICE_NAME = "device_name"
CONF_ADDRESS = "address"

# Coordinator
UPDATE_INTERVAL = 30  # seconds  (default; configurable via options flow)
UPDATE_INTERVAL_MIN = 10
UPDATE_INTERVAL_MAX = 600

# Options flow keys
CONF_UPDATE_INTERVAL = "update_interval"
CONNECT_TIMEOUT = 15.0  # seconds
COMMAND_TIMEOUT = 10.0  # seconds
PAIR_TIMEOUT = 60.0  # seconds - BLE pairing handshake can take a long time

# Number of presets
NUM_PRESETS = 3
