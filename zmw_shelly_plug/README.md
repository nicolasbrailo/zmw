# ZmwShellyPlug

Monitors a list of Shelly smart plugs over their local HTTP API and periodically broadcasts power/energy statistics over MQTT. Useful for tracking power consumption when integrated with other services like ZmwSensors.

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
