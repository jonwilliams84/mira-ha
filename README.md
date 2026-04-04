# Mira Mode for Home Assistant

A custom Home Assistant integration for controlling Mira Mode and Mira Activate digital showers and baths via Bluetooth Low Energy (BLE).

Works through ESPHome Bluetooth proxies — no USB dongle or direct BLE connection needed from your HA host.

## Features

- **BLE control via ESPHome proxies** — uses HA's Bluetooth integration to route through your existing ESPHome BLE proxy mesh
- **Config flow with guided pairing** — discover devices automatically, pair through the HA UI
- **Outlet switches** — independent on/off control for both outlets (shower head, bath fill, etc.)
- **Temperature control** — set target water temperature via a slider (20–45°C)
- **Water temperature sensor** — live actual water temperature reading
- **Preset buttons** — activate up to 3 saved presets on the device
- **Resilient BLE connection** — automatic reconnection, graceful error handling, pending state tracking to prevent outlet/temperature crosstalk

## Supported Devices

- Mira Mode digital shower

Any device advertising BLE service UUID `bccb0001-ca66-11e5-88a4-0002a5d5c51b` should work.

## Requirements

- Home Assistant 2024.1 or later
- A Bluetooth adapter accessible to HA — either:
  - ESPHome Bluetooth proxy (recommended)
  - USB Bluetooth adapter on the HA host
- The ESP32 or BLE adapter must be within Bluetooth range (~10m) of the Mira Mode device

## Installation

### Manual

1. Copy the `custom_components/mira_mode` directory to your Home Assistant config directory
2. Restart Home Assistant

### HACS (Manual Repository)

1. Open HACS in Home Assistant
2. Go to Integrations → three dots menu → Custom repositories
3. Add `https://github.com/jonwilliams84/mira-ha` as an Integration
4. Search for "Mira Mode" and install
5. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Mira Mode** — your devices should be auto-discovered via BLE
3. Select your device
4. **Pairing step**: Hold the outlet button on your Mira Mode unit for 5 seconds to put it in pairing mode (LED will flash), then click Submit in HA
5. The integration will pair and create entities automatically

## Entities

Per device, the integration creates:

| Entity | Type | Description |
|--------|------|-------------|
| Outlet 1 | Switch | On/off control for outlet 1 (e.g. shower head) |
| Outlet 2 | Switch | On/off control for outlet 2 (e.g. bath fill) |
| Temperature | Number | Target water temperature (20–45°C, 0.5° steps) |
| Water Temperature | Sensor | Actual measured water temperature |
| Preset 1/2/3 | Button | Activate saved presets |

## How It Works

The integration communicates with Mira Mode devices using a reverse-engineered BLE GATT protocol. During pairing, the device assigns a client slot and the integration stores a shared secret (client ID) used for CRC authentication on all subsequent commands.

All BLE traffic is routed through Home Assistant's Bluetooth integration, which automatically selects the best available Bluetooth adapter or ESPHome proxy.

## Troubleshooting

**Device not discovered**: Ensure your BLE proxy/adapter is within range. Check HA's Bluetooth integration for the device.

**Pairing fails**: Make sure the Mira Mode LED is flashing (hold outlet button 5 seconds). The pairing window is 60 seconds.

**Entities unavailable**: The BLE connection drops periodically — entities should recover within 30 seconds. Check HA logs with:
```yaml
logger:
  logs:
    custom_components.mira_mode: debug
```

**Outlet toggling affects the other outlet**: This was addressed with pending state tracking. If you still see issues, restart HA to clear stale state.

## Credits

- Protocol documentation by [Nigel Hannam](https://github.com/nhannam/shower-controller-documentation)
- Python reference implementation by [Alessandro Pilotti](https://github.com/alexpilotti/python-miramode)

## License

MIT
