# ZmwShellyPlug

Monitors a list of Shelly smart plugs over their local HTTP API and periodically broadcasts power/energy statistics over MQTT. Useful for tracking power consumption when integrated with other services like ZmwSensors.

![](README_screenshot.png)

## Configuration

| Key | Description |
|-----|-------------|
| `devices_to_monitor` | List of Shelly device IP addresses or hostnames to poll |
| `bcast_period_secs` | How often (in seconds) to broadcast device stats over MQTT |

## WWW

- `/` - Monitoring UI (served from `www/` directory)
- `/ls_devs` - JSON array of monitored device names
- `/all_stats` - JSON object mapping device names to their latest stats

## Notable Behavior

- Device stats are fetched in background threads to avoid blocking the broadcast timer. The first broadcast after startup may return empty data while the initial fetch completes.
- Devices that are offline (unreachable or missing WiFi info) are silently skipped in the periodic MQTT broadcast.
- Device configuration (name) is fetched once at startup and cached. If the initial fetch fails, the device IP is used as the name.

## MQTT

**Topic:** `zmw_shelly_plug`

### Commands

#### `ls_devs`

List monitored device names. Response published on ls_devs_reply

_No parameters._

#### `all_stats`

Get stats for all monitored devices. Response published on all_stats_reply

_No parameters._

#### `get_mqtt_description`

Return the MQTT API description for this service. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `<device_name>/stats`

Periodically published stats for each online Shelly plug (every bcast_period_secs)

| Param | Description |
|-------|-------------|
| `device_name` | Name of the Shelly device |
| `powered_on` | Whether the switch output is on |
| `active_power_watts` | Current power draw in watts |
| `voltage_volts` | Current voltage |
| `current_amps` | Current amperage |
| `temperature_c` | Device temperature in Celsius |
| `lifetime_energy_use_watt_hour` | Total energy usage in Wh |
| `last_minute_energy_use_watt_hour` | Energy used in the last minute in Wh |
| `device_current_time` | Device local time |
| `device_uptime` | Device uptime in seconds |
| `device_ip` | Device WiFi IP address |
| `online` | Whether the device is reachable |

#### `ls_devs_reply`

Response to ls_devs. List of device name strings

Payload: `['device_name_1', 'device_name_2']`

#### `all_stats_reply`

Response to all_stats. Map of device name to stats object

| Param | Description |
|-------|-------------|
| `<device_name>` | {'device_name': '...', 'active_power_watts': '...', '...': ' ...'} |

#### `get_mqtt_description_reply`

Response to get_mqtt_description. The MQTT API description for this service

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |
