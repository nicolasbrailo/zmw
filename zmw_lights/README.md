# ZmwLights

Zigbee light and switch discovery and control service. Connects to Zigbee2MQTT, discovers all light and switch devices on the network, and exposes them via a web UI and REST API.

## Features

- Automatically groups lights by name prefix. A set of lights like "TVRoomLight1", "TVRoomLight2", "TVRoomLight3" will be shown as "Light1", "Light2", "Light3" under group "TVRoom".
- Compact, mobile-friendly view of all discovered lights with quick brightness and on/off controls.
- Extended configuration panel for lights that support RGB, colour temperature, and light effects.
- Backend patches to normalize behaviour across different light models (e.g. adding RGB methods where only CIE XY is supported).
- Frontend caching via a device hash endpoint, allowing the UI to load full metadata only when the network changes.
- Switch support: switches are discovered and queryable alongside lights.
- User-defined actions: the React component accepts a map of `{label => url}` to render quick-action buttons within groups (e.g. scenes).

## Configuration

This service does not require a `config.json`. All configuration is provided via the Zigbee2MQTT connection settings inherited from the base MQTT config (typically `mqtt_ip` and `mqtt_port`).

## WWW Endpoints

- `/` - React UI for light and switch control (served from `www/` directory)
- `GET /get_lights` - JSON array of all discovered lights with their current state
- `GET /get_switches` - JSON array of all discovered switches with their current state
- `PUT /all_lights_on/prefix/<prefix>` - Turn on all lights whose name starts with `<prefix>` at 80% brightness
- `PUT /all_lights_off/prefix/<prefix>` - Turn off all lights whose name starts with `<prefix>`
- `GET /z2m/get_known_things_hash` - Hash of known devices (for cache invalidation)
- `GET /z2m/ls` - List of all known device names
- `GET /z2m/get_world` - Full state of all registered devices
- `GET /z2m/meta/<thing_name>` - Device capabilities metadata (large response)
- `PUT /z2m/set/<thing_name>` - Set device properties (e.g. `{"brightness": 50}`)
- `GET /z2m/get/<thing_name>` - Get current device properties

![](README_screenshot.png)
