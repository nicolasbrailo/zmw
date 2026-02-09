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

List of devices. Response on ls_devs_reply

_No parameters._

#### `all_stats`

Last stats for all devices. Response on all_stats_reply

_No parameters._

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `<device_name>/stats`

Periodically published stats for each online Shelly plug

| Param | Description |
|-------|-------------|
| `device_name` | Name |
| `powered_on` | Switch is on |
| `active_power_watts` | Power draw in watts |
| `voltage_volts` | Voltage |
| `current_amps` | Amperage |
| `temperature_c` | Device temperature |
| `lifetime_energy_use_watt_hour` | Total energy usage in Wh |
| `last_minute_energy_use_watt_hour` | Energy used in the last minute in Wh |
| `device_current_time` | Device local time |
| `device_uptime` | Device uptime in seconds |
| `device_ip` | Device WiFi IP address |
| `online` | Whether the device is reachable |

#### `ls_devs_reply`

List of devices

Payload: `['device_name_1', 'device_name_2']`

#### `all_stats_reply`

Map of device name to stats object

See `<device_name>/stats`

#### `get_mqtt_description_reply`

Service description

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |
