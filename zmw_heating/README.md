# ZmwHeating

Heating system manager that controls a boiler via a Zigbee on/off relay. Does not support OpenTherm or other advanced boiler protocols -- only simple on/off switching.

![](README_screenshot.png)

## Features

- **Schedule-based control**: 15-minute slot granularity. Each slot can be Always on, Always off, or Rule-based (decided by configured rules).
- **User overrides**: Boost button turns on heating for 1-12 hours. Off-now turns off until the next scheduled off slot.
- **Telegram integration**: Send `/tengofrio` via Telegram for a 1-hour heating boost. Receives notifications when the boiler turns on or off.
- **Rule-based heating**: Reads Zigbee2MQTT temperature sensors and applies rules:
  - `DefaultOff` / `DefaultOn` -- unconditional fallback rules.
  - `CheckTempsWithinRange` -- turns boiler on/off when any monitored sensor crosses min/max thresholds.
  - `ScheduledMinTargetTemp` -- targets a temperature range during a time window (with day-of-week filtering).
  - `PredictiveTargetTemperature` -- predictive variant of target temperature control.
- **Schedule persistence**: Active schedule and template survive service restarts via a persist file.

## Explainability

![](README_screenshot2.png)

Every state change carries a human-readable reason. The web UI and Telegram notifications explain exactly why the boiler is on or off (e.g. "Sensor TempSensor reports 18.94C, target is 20.0C between 08:00 and 09:00").

## Configuration

| Key | Description |
|-----|-------------|
| `zigbee_boiler_name` | Zigbee2MQTT device name of the on/off relay controlling the boiler |
| `rules` | List of rule objects. Each has a `name` field matching a rule class, plus rule-specific params |
| `schedule_persist_file` | Path to file where schedule state is saved and restored |

### Rule configuration examples

**CheckTempsWithinRange:**
```json
{"name": "CheckTempsWithinRange", "min_temp": 10, "max_temp": 30, "sensors": ["SensorName"], "metric": "temperature"}
```

**ScheduledMinTargetTemp:**
```json
{"name": "ScheduledMinTargetTemp", "sensor": "SensorName", "metric": "temperature", "start": "08:00", "end": "09:00", "days": "all", "target_min_temp": 19, "target_max_temp": 21}
```

## WWW Endpoints

- `/` -- Web UI for schedule management and status monitoring
- `/svc_state` -- JSON: current schedule, boiler state, sensor readings
- `/get_cfg_rules` -- JSON: configured heating rules
- `/active_schedule` -- JSON: today's active schedule
- `/boost=<hours>` -- Activate heating boost for N hours
- `/off_now` -- Turn heating off immediately
- `/slot_toggle=<name>` -- Toggle a schedule slot by HH:MM name
- `/template_slot_set=<hour,minute,allow_on>` -- Set a template slot
- `/template_apply` -- Apply template schedule to today
- `/template_reset=<state>` -- Reset all template slots to a state (Always/Never/Rule)
- `/template_schedule` -- JSON: active and template schedules

## MQTT

**Topic:** `zmw_heating`

### Commands

#### `svc_state`

Service state (schedule, boiler, sensors). Response on svc_state_reply

_No parameters._

#### `get_cfg_rules`

Get heating rules. Response on get_cfg_rules_reply

_No parameters._

#### `active_schedule`

Request today's schedule. Response on active_schedule_reply

_No parameters._

#### `boost`

Activate heating for N hours

| Param | Description |
|-------|-------------|
| `hours` | Number of hours to boost (1-12) |

#### `off_now`

Turn heating off immediately

_No parameters._

#### `slot_toggle`

Toggle a schedule slot on/off by time name

| Param | Description |
|-------|-------------|
| `slot_nm` | Slot time in HH:MM format |
| `reason?` | Reason to turn on/off |

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `svc_state_reply`

Current schedule, boiler state, sensor readings

| Param | Description |
|-------|-------------|
| `active_schedule` | List of schedule slots |
| `allow_on` | Current slot allow_on policy |
| `mqtt_thing_reports_on` | Boiler relay state value |
| `boiler_state_history` | Recent state changes |
| `monitoring_sensors` | Sensor name to current value map |

#### `get_cfg_rules_reply`

Configured temp-based rules

List of rule config objects

#### `active_schedule_reply`

Today's schedule starting from current slot

Payload: `[{'hour': 'int', 'minute': 'int', 'allow_on': 'Always|Never|Rule', 'request_on': 'bool', 'reason': 'str'}]`

#### `get_mqtt_description_reply`

Service description

This object
