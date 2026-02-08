# ZMW

ZMW will expose a Zigbee network as a small set of RESTish endpoints, and provide a basic UI to manage your Zigbee network with a web interface, with sensible defaults and minimal configuration. Clone, do `install_all_svcs.sh` and configure your network. Some things may work.

## What does it do?

The aim of the project is to read mqtt messages broadcasted by Zigbee2mqtt and translate them to objects with an API accessible through REST(ish) URLs, with a very limited set of dependencies, and very little configuration required. The goal is to enable developers to easily configure and extend a zigbee network using Python. The project core is small and extensible so that new thing types may be supported; even non-MQTT based things, like media players with 3rd party API integrations. The project includes extensions for Sonos, Spotify and possibly other non-MQTT things I find useful.

The server is designed to be low footprint, so that it may run in a RaspberryPi. Some time ago even an RPI W Zero might have worked, but now this project runs multiple services and a Zero is unlikely to be a good target anymore.

## Why?
A long time ago - almost 10 years ago? - after trying out Hassio, Home-Assistant and OpenHAB I figured I didn't like them. I'm not too keen on installing an entire OS and fiddling with yaml files for days just to make a button play a video. What to do with all my Zigbee hardware and home automation ideas, then? Easy: spend a week hacking my own. This is the result; not nearly as pretty as Hassio but easier to setup (or that was the case in 2017ish). And now I can add my own buttons using plain Python and HTML.

Who should use this? If you:

* Have a few Zigbee devices but don't want to use a proprietary solution
* Prefer programming Python to debugging yaml files and reading manuals
* Don't mind some hacking

You may find this project useful.

## New setup

* Clone the repo
* make systemdeps
* Install mosquitto and zigbee2mqtt (check out scripts/install_*.sh)
* make install_all_services
* Good luck.

## Architecture and Creating a new service

ZMW is pretty simple:

* zzmw_lib/www has all of the web helpers, including css and base app js helpers. An app needs to be started by its html.
* zzmw_lib/zzmw_lib/*mqtt* has different ZMW service base classes. Pick one for your new service.
* zzmw_lib/zzmw_lib/service_runner is what launches the service. It will start a flask server and your app in parallel, and handle things like journal logs and basic www styles
* zz2m is the proxy to zigbee2mqtt

Start a new service by copying an existing one. Then:

* The main app entry point should be the same name as your service directory. For example, if the service directory is called "zmw_foo", the main entry point for systemd will be "zmw_foo/zmw_foo.py". If your names don't match, the app will work but install and monitoring scripts will break.
* Build your impl in your py file, update the www entry point in www/index.html and www/app.js
* Update any deps in your rebuild_deps makefile target
* Build with `make rebuild_deps`, then `make rebuild_ui`
* Try it out with `make devrun`
* When ready, `make install_svc`. The service will now forever run in the background and you can monitor it from servicemon.

If you are developing a service that won't be upstreamed to zmw:

* common.mk won't work for you, as it will assume you are working on the root of the project. You will need to manager your own pipfile (or copypaste the zmw common makefile).

## Managing services

Install new services with `make rebuild_ui && make install_svc`. This will trigger the install_svc.sh helper script. Once installed, you can:

* Use config_apply and config_merge to manage all service config files from a single place.
* Use restart_and_log to restart a service and tail its logs.
* Use logs.sh to tail the logs of all services in the system.
* There is a restart_all helper that will shutdown and bringup services in an ordered way. This is unnecessary, but it prevents log spam and warnings in the logs while services boot up.
* If you need to refresh the code of a service, just restart it. Service CWD is the ~/run directory specified at install time, but code points to the git repo, making bugfixes easy to deploy.
* If you need to reinstall a service (eg because its dependencies changed, or because a systemd template or script was updated) type `make install_svc` again. The command is idempotent. It will shutdown and clean up the old service, then install the update.

All service management scripts are wrappers on top of systemd/systemctl/journalctl.


# Supported Services

# ZmwCatSnackDispenser

Manages an Aqara ZNCWWSQ01LM (aqara.feeder.acn001) cat food dispenser via Zigbee2MQTT. Handles feeding schedules, monitors dispense events, and sends Telegram notifications on success, failure, or missed feedings.

![](zmw_cat_snack_dispenser/README_screenshot.png)

## How It Works

The service uploads a feeding schedule to the Zigbee-connected dispenser unit, then monitors that the unit actually dispenses food at the scheduled times. If the unit misses a scheduled feeding (within a configurable tolerance), the service triggers an emergency remote dispense and sends an alert.

Dispense events are tracked regardless of source: scheduled, manual (button press on the unit), remote (Zigbee command), or requested via WWW/Telegram. Each event is logged in a rolling history with request/acknowledgement timestamps and portion counts.

## Configuration

| Key | Description |
|-----|-------------|
| `z2m_cat_feeder` | Zigbee2MQTT friendly name of the cat feeder device |
| `schedule_tolerance_secs` | Seconds to wait after a scheduled feeding before declaring it missed and triggering emergency dispense |
| `feeding_schedule` | List of schedule entries, each with `days`, `hour`, `minute`, `serving_size` |
| `telegram_on_error` | Send a Telegram message when a dispense event fails |
| `telegram_on_success` | Send a Telegram message on every successful dispense |
| `telegram_day_summary` | Send a daily summary after the last scheduled feeding |
| `telegram_summary_delay_minutes` | Minutes after last scheduled feeding to send the daily summary (default 5) |

### Schedule entry format

```json
{"days": "everyday", "hour": 17, "minute": 7, "serving_size": 1}
```

Valid `days` values: `everyday`, `workdays`, `weekend`, `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`, `mon-wed-fri-sun`, `tue-thu-sat`.

## WWW Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | React monitoring UI |
| `/feed_now` | GET | Trigger an immediate dispense |
| `/feed_history` | GET | JSON array of recent dispense events |
| `/feed_schedule` | GET | JSON array of the current feeding schedule |
| `/save_schedule` | PUT | Upload a new feeding schedule (JSON body). Validates and writes to config.json; service restarts automatically |

## Telegram Integration

On startup, registers a `/dispensecatsnacks` bot command with ZmwTelegram. Sends notifications for:
- Successful dispense events (if `telegram_on_success` is enabled)
- Failed or missed dispense events (if `telegram_on_error` is enabled)
- Daily feeding summary (if `telegram_day_summary` is enabled)

## Config Enforcement

The service continuously ensures the physical unit is configured correctly:
- Mode is set to `schedule` (not manual)
- The unit's internal schedule matches the configured `feeding_schedule`

If a mismatch is detected, the service corrects it automatically. A 1-second backoff prevents message loops when the unit echoes back partial config states.

## MQTT

**Topic:** `zmw_cat_feeder`

### Commands

#### `feed_now`

Dispense food immediately. Response published on feed_now_reply

| Param | Description |
|-------|-------------|
| `source` | (optional) Who/what triggered this request |
| `serving_size` | (optional) Number of portions to dispense |

#### `get_history`

Request dispensing history. Response published on get_history_reply

_No parameters._

#### `get_schedule`

Request the current feeding schedule. Response published on get_schedule_reply

_No parameters._

#### `get_mqtt_description`

Request MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `feed_now_reply`

Result of a feed_now command

| Param | Description |
|-------|-------------|
| `status` | 'ok' or 'error' |
| `error` | (only on failure) Error description |

#### `get_history_reply`

Response to get_history. List of dispensing event objects

Payload: `[{'dispense_event_id': 'int or null', 'time_requested': 'ISO timestamp', 'source': 'What triggered this (Schedule, Telegram, WWW, etc.)', 'portions_dispensed': 'int or null', 'weight_dispensed': 'int or null', 'unit_acknowledged': 'bool', 'error': 'string or null'}]`

#### `get_schedule_reply`

Response to get_schedule. List of schedule entry objects

Payload: `[{'days': 'Day specifier (everyday, workdays, weekend, mon, etc.)', 'hour': '0-23', 'minute': '0-59', 'serving_size': 'int'}]`

#### `get_mqtt_description_reply`

Response to get_mqtt_description. Full MQTT API description dict

# ZmwContactMon

Contact sensor monitoring with timeout and curfew alerts. Monitors Zigbee contact sensors (doors, windows) and triggers configured actions when sensors change state, time out, or violate curfew.

## Configuration

| Key | Description |
|-----|-------------|
| `actions` | Dict of sensor_name -> event -> action mappings (see Actions below) |
| `curfew_hour` | (optional) Time in `HH:MM` format for daily curfew check |
| `chime_skip_default_secs` | Default duration (seconds) for skip-chimes requests |
| `chime_skip_max_secs` | Maximum allowed skip-chimes duration (seconds) |

### Actions

Each sensor in `actions` maps event types to action handlers:

**Events:** `open`, `close`, `timeout`, `curfew`
**Metadata:** `normal_state` (bool, required), `timeout_secs` (int, required if `timeout` event is defined)

**Action types:**

| Action | Description | Required params |
|--------|-------------|-----------------|
| `telegram` | Send a message via ZmwTelegram | `msg` |
| `whatsapp` | Send a message via ZmwWhatsapp | `msg` |
| `tts_announce` | Broadcast a TTS message via ZmwSpeakerAnnounce | `msg`, `lang` |
| `sound_asset_announce` | Play a sound file via ZmwSpeakerAnnounce | `local_path` or `public_www` |

## WWW

- `/` - React monitoring UI (served from `www/` directory)
- `/svc_state` - JSON: current sensor states, contact history, chime skip status
- `/skip_chimes` - Skip chime notifications for the default duration
- `/skip_chimes_with_timeout/<secs>` - Skip chime notifications for specified seconds
- `/enable_chimes` - Re-enable chime notifications immediately
- `/test_curfew` - Manually trigger a curfew check (debug)

## Curfew

When `curfew_hour` is configured, a daily check runs at that time. Any sensor in a non-normal state triggers its `curfew` action (if defined).

## Dependencies

- `ZmwSpeakerAnnounce` - for TTS and sound asset announcements
- `ZmwWhatsapp` - for WhatsApp notifications
- `ZmwTelegram` - for Telegram notifications

## MQTT

**Topic:** `zmw_contactmon`

### Commands

#### `skip_chimes`

Temporarily disable chime/sound notifications

| Param | Description |
|-------|-------------|
| `timeout` | (optional) Duration in seconds to skip chimes. Uses configured default if omitted. |

#### `enable_chimes`

Re-enable chime notifications immediately, cancelling any pending skip timeout

_No parameters._

#### `publish_state`

Request current service state. Response published on publish_state_reply

_No parameters._

#### `get_mqtt_description`

Request MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `publish_state_reply`

Response to publish_state command with full service state. Also published after skip_chimes, enable_chimes, or publish_state. Contains full service state

| Param | Description |
|-------|-------------|
| `sensors` | Dict of sensor_name -> {in_normal_state, contact, ...} |
| `history` | List of recent contact state changes |
| `skipping_chimes` | Boolean, true if chimes are currently suppressed |
| `skipping_chimes_timeout_secs` | Seconds until chimes re-enable, or null |

#### `<sensor_name>/contact`

Published when a contact sensor changes state

| Param | Description |
|-------|-------------|
| `sensor` | Name of the sensor |
| `contact` | Current contact state |
| `prev_contact` | Previous contact state |
| `entering_non_normal` | Previous contact state (indicates if entering non-normal) |

#### `get_mqtt_description_reply`

Response to get_mqtt_description with this API description

(this object)

# ZmwCronenbergs

Scheduled home automation service. Runs calendar-based cron jobs for lights, notifications, and device health monitoring.

## Features

- **Auto lights off**: At a configured day/time, checks if any lights were left on, turns them off, and logs the event. Useful for weekday mornings after everyone leaves the house.
- **Vacation mode**: Simulates occupancy by turning random lights on in the late afternoon, dimming them in the evening, and shutting everything off at night.
- **Speaker announcements**: Plays scheduled TTS announcements through speakers at configured times (e.g. daily reminders).
- **Battery alerts**: Weekly check (Sundays at 10:00) for devices with battery below 30%, sends a Telegram notification listing them.

## Configuration

| Key | Description |
|-----|-------------|
| `auto_lights_off.enable` | Enable the automatic lights-off check |
| `auto_lights_off.day_of_week` | Cron day-of-week string (e.g. `"mon-fri"`) |
| `auto_lights_off.time` | Time to check, as `"HH:MM"` |
| `vacations_mode.enable` | Enable vacation mode light simulation |
| `vacations_mode.late_afternoon` | Time to turn random lights on, as `"HH:MM"` |
| `vacations_mode.evening` | Time to dim lights, as `"HH:MM"` |
| `vacations_mode.night` | Time to turn all lights off, as `"HH:MM"` |
| `speaker_announce` | List of `{time, msg, lang, vol}` objects for scheduled TTS |

## WWW

- `/` - React monitoring UI (served from `www/` directory)
- `/stats` - JSON object with light check history, vacation mode status, speaker announce config, and battery device data
- `/mock_auto_lights_off` - Debug: inserts mock light-check entries into history
- `/test_low_battery_notifs` - Debug: triggers a battery check immediately
- `/test_vacations_mode_late_afternoon` - Debug: triggers the vacation late-afternoon phase
- `/test_vacations_mode_evening` - Debug: triggers the vacation evening phase
- `/test_vacations_mode_night` - Debug: triggers the vacation night phase

## Service Dependencies

- **ZmwTelegram** - Used to send battery alert notifications and vacation mode status messages
- **ZmwSpeakerAnnounce** - Used to play scheduled TTS announcements

![](zmw_cronenbergs/README_screenshot.png)

## MQTT

**Topic:** `zmw_cronenbergs`

### Commands

#### `get_stats`

Request service stats (light check history, vacation mode status, battery info). Response published on get_stats_reply

_No parameters._

### Announcements

#### `get_stats_reply`

Response to get_stats with full service statistics

| Param | Description |
|-------|-------------|
| `light_check_history` | List of recent light check events |
| `vacations_mode` | Whether vacation mode is enabled |
| `speaker_announce` | Configured speaker announcements |
| `battery_things` | List of devices with battery levels |

#### `get_mqtt_description_reply`

Response to get_mqtt_description with this service's MQTT API

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |

# ZmwDashboard

Dashboard system that ties all other ZMW services to a mobile friendly interface.

![](zmw_dashboard/README_screenshot.png)

This service integrates with all other ZMW services running in the system to

* Enable quick lights control.
* Exposes scenes ("fake" buttons created by a user-service, which perform a set of actions on other ZmwServices). These are grouped together with lights, so that each group of lights has a set of scenes/action-buttons assigned to it.
* Exposes a list of sensors, by default showing temperature.
* Speaker-announce: send an announcement through the Sonos LAN speakers in your network (user recording not supported here: running the dashboard via HTTPS with a self-signed cert is painful!)
* Each section (lights, scenes, sensors, cameras...) can link to the main service, which exposes further functionality.
* Contact monitoring: expose door states, and lets you bypass chimes (if your door is configured to play a chime when open).
* Heating: monitor heating state and turn it on/off
* Doorbell cam: show last snap of the doorbell camera, and lets you take a new one. Also displays if the doorbell has rung recently.
* Theming: supports Classless CSS themes.
* Links to user-defined services: add more links to all of those services running in your LAN, so you have a centralised place to access them.
* System alerts: display any system level alerts, such as services down or your cat running out of food.


# ZmwDoorman

Doorbell event handler and notification coordinator. Orchestrates door events from a Reolink camera and contact sensor, playing announcement sounds, sending photos via WhatsApp/Telegram, and managing a door-open lighting scene.

![](zmw_doorman/README_screenshot.png)

## Configuration

| Key | Description |
|-----|-------------|
| `doorbell_announce_volume` | Volume level for speaker announcements on button press |
| `doorbell_announce_sound` | Sound file name (served from `www/` directory) to play on button press |
| `doorbell_contact_sensor` | Name of the Zigbee contact sensor on the door |
| `doorbell_cam_host` | Hostname/IP of the Reolink doorbell camera |
| `door_open_scene_thing_to_manage` | List of Zigbee light names to control in the door-open scene |
| `door_open_scene_timeout_secs` | Seconds before the door-open scene auto-expires |
| `latlon` | `[lat, lon]` for sunrise/sunset calculation (door-open scene only activates when dark) |

## Service Dependencies

- **ZmwSpeakerAnnounce** -- plays doorbell chime sound
- **ZmwWhatsapp** -- sends motion/doorbell photos via WhatsApp
- **ZmwTelegram** -- sends motion/doorbell photos via Telegram, handles `/door_snap` command
- **ZmwReolinkCams** -- provides camera snapshots, doorbell button press, and motion events
- **ZmwContactmon** -- provides door contact sensor open/close events and chime control

## WWW Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/` | GET | React monitoring UI (served from `www/` directory) |
| `/stats` | GET | JSON: door statistics (press counts, motion counts, event history) |
| `/contactmon_state` | GET | JSON: current contact monitor state (proxied from ZmwContactmon) |
| `/request_snap` | PUT | Request a new snapshot from the doorbell camera |
| `/skip_chimes` | PUT | Skip pending contact sensor chimes; returns updated state |
| `/get_snap/<filename>` | GET | Serve a camera snapshot image by filename |
| `/get_cams_svc_url` | GET | JSON: URL of the ZmwReolinkCams web UI |
| `/get_contactmon_svc_url` | GET | JSON: URL of the ZmwContactmon web UI |

## Door-Open Scene

When the door contact sensor reports the door opening and it is dark outside (based on sun position at the configured lat/lon), the service turns on a set of configured Zigbee lights. The scene auto-expires after a configurable timeout. If another service or user manually controls a managed light while the scene is active, that light is released from management. Motion events at the door extend the scene timer.

## Telegram Integration

Registers a `/door_snap` command with ZmwTelegram. When invoked, requests a snapshot from the doorbell camera and sends it back over Telegram. Snap requests that take longer than 5 seconds are discarded.

## MQTT

**Topic:** `zmw_doorman`

### Commands

#### `get_stats`

Request door statistics (doorbell presses, motion events, door opens). Response published on get_stats_reply

_No parameters._

#### `get_mqtt_description`

Request the MQTT interface description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `on_doorbell_pressed`

Published when the doorbell button is pressed

| Param | Description |
|-------|-------------|
| `snap_path` | Path to camera snapshot (may be null) |

#### `on_motion_detected`

Published when motion is detected at the door camera

| Param | Description |
|-------|-------------|
| `snap_path` | Path to camera snapshot (may be null) |

#### `on_motion_cleared`

Published when the door motion event ends (vacancy reported or timeout)

#### `on_door_opened`

Published when the door contact sensor reports the door opened

#### `on_door_closed`

Published when the door contact sensor reports the door closed

#### `get_stats_reply`

Response to get_stats command with current door statistics

| Param | Description |
|-------|-------------|
| `doorbell_press_count_today` | int |
| `motion_detection_count_today` | int |
| `last_snap` | filename or null |
| `last_snap_time` | epoch or null |
| `history` | list of event records |
| `motion_in_progress` | bool |
| `door_open_in_progress` | bool |

#### `get_mqtt_description_reply`

Response to get_mqtt_description with this service's MQTT interface

| Param | Description |
|-------|-------------|
| `commands` | ... |
| `announcements` | ... |

# ZmwHeating

Heating system manager that controls a boiler via a Zigbee on/off relay. Does not support OpenTherm or other advanced boiler protocols -- only simple on/off switching.

![](zmw_heating/README_screenshot.png)

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

![](zmw_heating/README_screenshot2.png)

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

Request current service state (schedule, boiler, sensors). Response on svc_state_reply

_No parameters._

#### `get_cfg_rules`

Request configured heating rules. Response on get_cfg_rules_reply

_No parameters._

#### `active_schedule`

Request today's active schedule. Response on active_schedule_reply

_No parameters._

#### `boost`

Activate heating boost for N hours

| Param | Description |
|-------|-------------|
| `hours` | Number of hours to boost (1-12) |

#### `off_now`

Turn heating off immediately until next scheduled off slot

_No parameters._

#### `slot_toggle`

Toggle a schedule slot on/off by time name

| Param | Description |
|-------|-------------|
| `slot_nm` | Slot time in HH:MM format |
| `reason` | [Optional] Reason to turn on/off |

#### `get_mqtt_description`

Request MQTT API description. Response on get_mqtt_description_reply

_No parameters._

### Announcements

#### `svc_state_reply`

Response to svc_state: current schedule, boiler state, and sensor readings

| Param | Description |
|-------|-------------|
| `active_schedule` | List of schedule slots |
| `allow_on` | Current slot allow_on policy |
| `mqtt_thing_reports_on` | Boiler relay state value |
| `boiler_state_history` | Recent state changes |
| `monitoring_sensors` | Sensor name to current value map |

#### `get_cfg_rules_reply`

Response to get_cfg_rules: the raw rules configuration

List of rule config objects

#### `active_schedule_reply`

Response to active_schedule: today's schedule starting from current slot

Payload: `[{'hour': 'int', 'minute': 'int', 'allow_on': 'Always|Never|Rule', 'request_on': 'bool', 'reason': 'str'}]`

#### `get_mqtt_description_reply`

Response to get_mqtt_description: this service's MQTT API

This object structure

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

![](zmw_lights/README_screenshot.png)

## MQTT

**Topic:** `zmw_lights`

### Commands

#### `get_lights`

Request state of all discovered lights. Response published on get_lights_reply

_No parameters._

#### `get_switches`

Request state of all discovered switches. Response published on get_switches_reply

_No parameters._

#### `all_lights_on`

Turn on all lights matching a name prefix at 80% brightness. Response published on all_lights_on_reply

| Param | Description |
|-------|-------------|
| `prefix` | Name prefix to filter lights (e.g. 'TVRoom') |

#### `all_lights_off`

Turn off all lights matching a name prefix. Response published on all_lights_off_reply

| Param | Description |
|-------|-------------|
| `prefix` | Name prefix to filter lights (e.g. 'TVRoom') |

#### `get_mqtt_description`

Request the MQTT API description for this service. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `get_lights_reply`

Response to get_lights. JSON array of light state objects

Payload: `[{'name': 'Light name', 'state': 'ON/OFF', 'brightness': '0-255', '...': 'other device-specific fields'}]`

#### `get_switches_reply`

Response to get_switches. JSON array of switch state objects

Payload: `[{'name': 'Switch name', 'state': 'ON/OFF'}]`

#### `all_lights_on_reply`

Confirmation that all_lights_on completed

| Param | Description |
|-------|-------------|
| `status` | ok |

#### `all_lights_off_reply`

Confirmation that all_lights_off completed

| Param | Description |
|-------|-------------|
| `status` | ok |

#### `get_mqtt_description_reply`

The MQTT API description for this service

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |

# ZmwReolinkCams

Multi-camera Reolink service with motion detection, doorbell events, recording, and an NVR-like web interface. Connects to one or more Reolink cameras via webhook/ONVIF, broadcasts events over MQTT, and provides snapshot/recording controls.

![](zmw_reolink_cams/README_screenshot.png)

## Configuration

| Key | Description |
|-----|-------------|
| `cameras` | Array of camera configs, each with at least `cam_host` (hostname/IP) |
| `cameras[].is_doorbell` | (optional) Set `true` if camera is a doorbell model |
| `rec_path` | Directory for storing recordings, organized by camera |
| `snap_path_on_movement` | (optional) Directory for motion-triggered snapshots |

## WWW Endpoints

### Camera Controls
- `/ls_cams` - JSON list of currently online camera hostnames
- `/snap/<cam_host>` - Capture and return a new snapshot (JPEG)
- `/lastsnap/<cam_host>` - Return the last saved snapshot (JPEG)
- `/record/<cam_host>?secs=N` - Start recording for N seconds (5-120)

### Camera Webhooks
- `/cam/<cam_host>` - Webhook endpoint for camera events (GET/POST, used internally by camera firmware)

### NVR Web Interface
- `/nvr` - NVR web UI for browsing recordings and snapshots
- `/nvr/api/cameras` - JSON list of cameras with recordings on disk
- `/nvr/api/<cam>/recordings?days=N` - JSON list of recordings for a camera (optionally filtered by age)
- `/nvr/api/<cam>/snapshots` - JSON list of snapshots for a camera
- `/nvr/<cam>/get_recording/<file>` - Serve a recording file
- `/nvr/<cam>/get_snapshot/<file>` - Serve a snapshot file

## NVR Behavior

![](zmw_reolink_cams/README_screenshot2.png)

Unlike a traditional NVR, this service does not record continuously. Recording starts only when the camera reports motion or a doorbell press. This means the first few seconds of an event may be missed, but saves significant energy and storage. Recordings are re-encoded in the background for web-friendly playback.

## Doorbell Alerts

When a doorbell camera button is pressed, the service tracks it for 60 seconds. During this window, `get_service_alerts()` reports an active doorbell alert. Cameras that fail to connect are also reported as alerts.

## Integrations

This service integrates with ZmwDoorman to:
- Send Telegram notifications on doorbell press
- Play audio chimes over LAN speakers on doorbell press
- Send WhatsApp messages on motion detection

See the ZmwDoorman README for details.

## MQTT

**Topic:** `zmw_reolink_cams`

### Commands

#### `snap`

Take a snapshot from a camera. Response published on on_snap_ready

| Param | Description |
|-------|-------------|
| `cam_host` | Camera host identifier |

#### `rec`

Start recording on a camera

| Param | Description |
|-------|-------------|
| `cam_host` | Camera host identifier |
| `secs` | Recording duration in seconds |

#### `ls_cams`

List online cameras. Response published on ls_cams_reply

_No parameters._

#### `get_mqtt_description`

Get MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `on_snap_ready`

Snapshot captured and ready

| Param | Description |
|-------|-------------|
| `event` | on_snap_ready |
| `cam_host` | Camera host identifier |
| `snap_path` | Local path to snapshot file |

#### `on_doorbell_button_pressed`

Doorbell button was pressed

| Param | Description |
|-------|-------------|
| `event` | on_doorbell_button_pressed |
| `cam_host` | Camera host |
| `snap_path` | Path to snapshot |
| `full_cam_msg` | Raw camera event data |

#### `on_motion_detected`

Camera detected motion

| Param | Description |
|-------|-------------|
| `event` | on_motion_detected |
| `cam_host` | Camera host |
| `path_to_img` | Path to motion snapshot |
| `motion_level` | Motion intensity level |
| `full_cam_msg` | Raw camera event data |

#### `on_motion_cleared`

Motion cleared by camera

| Param | Description |
|-------|-------------|
| `event` | on_motion_cleared |
| `cam_host` | Camera host |
| `full_cam_msg` | Raw camera event data |

#### `on_motion_timeout`

Motion event timed out without camera reporting clear

| Param | Description |
|-------|-------------|
| `event` | on_motion_timeout |
| `cam_host` | Camera host |
| `timeout` | Timeout value |

#### `on_new_recording`

A new recording completed and is available

| Param | Description |
|-------|-------------|
| `event` | on_new_recording |
| `cam_host` | Camera host |
| `path` | Local path to recording file |

#### `on_recording_failed`

Recording failed

| Param | Description |
|-------|-------------|
| `event` | on_recording_failed |
| `cam_host` | Camera host |
| `path` | Path of failed recording |

#### `on_reencoding_ready`

Re-encoding of a recording completed

| Param | Description |
|-------|-------------|
| `event` | on_reencoding_ready |
| `cam_host` | Camera host |
| `orig_path` | Original recording path |
| `reencode_path` | Re-encoded file path |

#### `on_reencoding_failed`

Re-encoding of a recording failed

| Param | Description |
|-------|-------------|
| `event` | on_reencoding_failed |
| `cam_host` | Camera host |
| `path` | Path of failed re-encode |

#### `ls_cams_reply`

Response to ls_cams. List of online camera host identifiers

Payload: `['cam_host_1', 'cam_host_2']`

#### `get_mqtt_description_reply`

Response to get_mqtt_description. Full MQTT API description

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |

# ZmwSensormon

Sensor data monitoring and history service. Monitors Zigbee sensors (via Z2M), Shelly plugs (via ZmwShelly), and outside weather (via Open-Meteo), storing historical readings in a SQLite database.

![](zmw_sensormon/README_screenshot.png)

## Features

- Monitors MQTT sensors: temperature, humidity, power, battery, contact, occupancy, voltage, energy, PM2.5, VOC, and more.
- Stores time-series readings in SQLite with configurable retention (by days).
- Computes virtual metrics from real ones (e.g. feels-like temperature from temperature + humidity).
- Integrates with Shelly plugs via the `zmw_shelly_plug` MQTT topic.
- Fetches outside weather (temperature, humidity) from the Open-Meteo API on a 5-minute interval.
- Provides a React UI with sensor badges and historical charts.

## Configuration

| Key | Description |
|-----|-------------|
| `db_path` | Path to the SQLite database file for sensor history |
| `retention_days` | Number of days of history to retain |
| `outside_latitude` | Latitude for outside weather queries |
| `outside_longitude` | Longitude for outside weather queries |

Standard keys (`mqtt_ip`, `mqtt_port`, `http_host`, `http_port`) are also supported.

## WWW Endpoints

| Endpoint | Description |
|----------|-------------|
| `/` | React monitoring UI (sensor badges, charts) |
| `/sensors/ls` | List all known sensor names (JSON array) |
| `/sensors/metrics` | List all known metric names (JSON array) |
| `/sensors/metrics/<sensor_name>` | List metrics available for a specific sensor |
| `/sensors/measuring/<metric>` | List sensors that measure a specific metric |
| `/sensors/get/<name>` | Get current values for a sensor (JSON dict). Checks Shelly devices first, then Z2M |
| `/sensors/get_all/<metric>` | Get current value of a metric across all sensors (JSON dict of sensor name to value) |
| `/sensors/get_metric_in_sensor_csv/<sensor>/<metric>` | Historical readings of one metric in one sensor (CSV) |
| `/sensors/get_metric_in_sensor_csv/<sensor>/<metric>/history/<unit>/<time>` | Same, with time window |
| `/sensors/get_all_metrics_in_sensor_csv/<sensor>` | All historical readings for one sensor (CSV) |
| `/sensors/get_single_metric_in_all_sensors_csv/<metric>` | One metric across all sensors (CSV) |
| `/sensors/get_single_metric_in_all_sensors_csv/<metric>/<unit>/<time>` | Same, with time window |
| `/sensors/gc_dead_sensors` | Trigger garbage collection of old sensor data |
| `/z2m/*` | Z2M web service endpoints |

## Virtual Metrics

When a sensor reports both `temperature` and `humidity`, a `feels_like_temp` virtual metric is automatically computed and stored:

- Hot+humid (T >= 27C, RH >= 40%): heat index (Rothfusz regression)
- Cold+humid (T < 20C, RH > 45%): humid-cold adjustment
- Otherwise: actual temperature

## Data Retention

Old samples are automatically purged daily at 02:22 based on the configured `retention_days`.

## MQTT

**Topic:** `zmw_sensormon`

### Commands

#### `get_sensor_values`

Get current values for a named sensor (Zigbee, Shelly, or virtual). Response on get_sensor_values_reply

| Param | Description |
|-------|-------------|
| `name` | Sensor name (e.g. 'Living_Room', 'Weather') |

#### `get_all_sensor_values`

Get the current value of a specific metric across all sensors that measure it. Response on get_all_sensor_values_reply

| Param | Description |
|-------|-------------|
| `metric` | Metric name (e.g. 'temperature', 'humidity', 'power_a') |

#### `get_known_sensors`

List all known sensor names. Response on get_known_sensors_reply

_No parameters._

#### `get_known_metrics`

List all metrics being measured across all sensors. Response on get_known_metrics_reply

_No parameters._

#### `get_sensors_measuring`

List sensors that measure a specific metric. Response on get_sensors_measuring_reply

| Param | Description |
|-------|-------------|
| `metric` | Metric name to query |

#### `get_mqtt_description`

Returns this MQTT API description. Response on get_mqtt_description_reply

_No parameters._

### Announcements

#### `get_sensor_values_reply`

Response to get_sensor_values. Dict of metric name to current value

| Param | Description |
|-------|-------------|
| `<metric>` | <value> |

#### `get_all_sensor_values_reply`

Response to get_all_sensor_values. Dict of sensor name to metric value

| Param | Description |
|-------|-------------|
| `<sensor_name>` | <value> |

#### `get_known_sensors_reply`

Response to get_known_sensors. List of sensor name strings

Payload: `['<sensor_name>']`

#### `get_known_metrics_reply`

Response to get_known_metrics. List of metric name strings

Payload: `['<metric_name>']`

#### `get_sensors_measuring_reply`

Response to get_sensors_measuring. List of sensor name strings

Payload: `['<sensor_name>']`

#### `get_mqtt_description_reply`

Response to get_mqtt_description. The MQTT API description dict

# ZmwServicemon

Monitors all other running z2m services, tracks their status (up/down), and monitors systemd journal for errors. Provides a dashboard view of system health.

![](zmw_servicemon/README_screenshot.png)

This service will let you know the health of your ZMW services at a glance. It will

* Display the list of running services (or when a service was last seen, if it's not running).
* Let you read detailed logs of each service.
* Provide a quick link to each service.
* Display the systemd status of a service (a systemd service may be running, but not registered as a ZMW service. A ZMW service may also be running, but not registered to systemd).
* Display a list of errors: ZmwServicemon will tail the journal for each ZMW service, and will capture errors and warnings. These will be displayed in ZmwServicemon www.
* Optional Telegram integration: integrates with ZmwTelegram to send you a message when the system encounters an error.


# ZmwShellyPlug

Monitors a list of Shelly smart plugs over their local HTTP API and periodically broadcasts power/energy statistics over MQTT. Useful for tracking power consumption when integrated with other services like ZmwSensors.

![](zmw_shelly_plug/README_screenshot.png)

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

# ZmwSonosCtrl

Manages Sonos speaker groups and audio source selection. Discovers Sonos speakers on the local network, creates speaker groups, and hijacks Spotify playback to Sonos via the SoCo library. Provides both a web UI and MQTT interface for playback control.

## Dependencies

- **ZmwSpotify** - Used to fetch the current Spotify playback context (playlist URI, track offset) before redirecting playback to Sonos speakers.

## Configuration

This service reads its configuration from the standard `cfg` dict. No service-specific keys are required beyond the base `ZmwMqttService` configuration. Speaker discovery happens automatically via SoCo's network scan.

The Spotify-to-Sonos URI conversion uses a hardcoded Sonos magic URI (`sid=9&flags=8232&sn=6`). If this stops working, play a Spotify playlist from the Sonos app and inspect the URIs reported by the `/get_sonos_play_uris` endpoint to extract the correct values.

## WWW

- `/` - React UI for speaker group management and playback control (served from `www/` directory)
- `/world_state` - JSON: full Sonos network state (speakers, groups, zones). Cached for 30 seconds.
- `/ls_speakers` - JSON: list of discovered speaker names
- `/get_sonos_play_uris` - JSON: map of speaker name to currently-playing URI
- `/get_spotify_context` - JSON: current Spotify playback context (fetched from ZmwSpotify)
- `/stop_all_playback` - PUT: stops all playback and resets speaker group state
- `/volume` - PUT: set volume for specific speakers (JSON body: `{"SpeakerName": 50, ...}`)
- `/volume_up` - PUT/GET: increase volume on the active speaker group
- `/volume_down` - PUT/GET: decrease volume on the active speaker group
- `/next_track` - PUT/GET: skip to next track
- `/prev_track` - PUT/GET: skip to previous track

### WebSocket endpoints

- `/spotify_hijack` - Send a JSON speaker config to initiate Spotify hijack with real-time status updates. Expected payload: `{"SpeakerName": {"vol": 50}, ...}`
- `/line_in_requested` - (unimplemented) Intended for line-in source switching

## Spotify Hijack Flow

1. Fetches current Spotify state from ZmwSpotify via MQTT
2. Extracts the playlist/album URI and current track offset
3. Discovers and resets the requested Sonos speakers
4. Creates a speaker group with the first speaker as coordinator
5. Sets volumes per the provided configuration
6. Attempts playback via SoCo ShareLink, then falls back to direct URI methods
7. Optionally seeks to the current track offset

## MQTT

**Topic:** `zmw_sonos_ctrl`

### Commands

#### `prev_track`

Skip to the previous track on the active speaker group

_No parameters._

#### `next_track`

Skip to the next track on the active speaker group

_No parameters._

#### `volume_up`

Increase volume on the active speaker group

| Param | Description |
|-------|-------------|
| `vol` | (optional) Volume step percentage, default 5 |

#### `volume_down`

Decrease volume on the active speaker group

| Param | Description |
|-------|-------------|
| `vol` | (optional) Volume step percentage, default 5 |

#### `spotify_hijack`

Hijack Spotify playback to a set of Sonos speakers

| Param | Description |
|-------|-------------|
| `<speaker_name>` | {'vol': 'Volume level (0-100)'} |

#### `spotify_hijack_or_toggle_play`

If playing, pause. If paused, resume. Otherwise, start a new Spotify hijack

| Param | Description |
|-------|-------------|
| `<speaker_name>` | {'vol': 'Volume level (0-100)'} |

#### `stop_all`

Stop all playback and reset Sonos speaker states

_No parameters._

#### `world_state`

Request full Sonos network state. Response published on world_state_reply

_No parameters._

#### `ls_speakers`

Request list of discovered speaker names. Response published on ls_speakers_reply

_No parameters._

#### `get_sonos_play_uris`

Request URIs currently playing on all speakers. Response published on get_sonos_play_uris_reply

_No parameters._

#### `get_spotify_context`

Request current Spotify context/state. Response published on get_spotify_context_reply

_No parameters._

#### `get_mqtt_description`

Request MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `world_state_reply`

Response to world_state command

| Param | Description |
|-------|-------------|
| `speakers` | List of speaker state dicts |
| `groups` | Map of coordinator name to member names |
| `zones` | List of zone names |

#### `ls_speakers_reply`

Response to ls_speakers command

Payload: `['List of speaker name strings']`

#### `get_sonos_play_uris_reply`

Response to get_sonos_play_uris command

| Param | Description |
|-------|-------------|
| `<speaker_name>` | URI string currently playing |

#### `get_spotify_context_reply`

Response to get_spotify_context command

| Param | Description |
|-------|-------------|
| `media_info` | Spotify media info dict including context URI and current track |

#### `get_mqtt_description_reply`

Response to get_mqtt_description command

| Param | Description |
|-------|-------------|
| `commands` | ... |
| `announcements` | ... |

# ZmwSpeakerAnnounce

Sonos speaker announcement service with TTS, pre-recorded asset playback, and live microphone recording support. Announcements are broadcast to all discovered Sonos speakers on the network.

![](zmw_speaker_announce/README_screenshot.png)

## Modes

- **TTS**: Send a text phrase to be converted to speech and played on all speakers. Multiple languages are supported via the configured TTS engine.
- **Asset playback**: Play a pre-existing audio file by name (from the asset cache), by local file path (copied to cache first), or by public URL.
- **User recording**: Record audio from your device microphone via the web UI, then broadcast it. Requires HTTPS (browsers block microphone access without SSL). The server uses a self-signed certificate, so a browser security warning is expected.

## Configuration

| Key | Description |
|-----|-------------|
| `announce_volume` | Default volume (0-100) for announcements |
| `tts_default_lang` | Default language code for TTS (e.g. `en`) |
| `tts_assets_cache_path` | Directory for cached TTS audio files and saved assets |
| HTTPS cert/key settings | Passed to `HttpsServer` for microphone recording support (see `https_server.py`) |

## WWW

- `/` - Web UI for TTS input and microphone recording (served from `www/` directory, available over both HTTP and HTTPS)
- `/announce_tts?phrase=X&lang=X&vol=N` - Trigger a TTS announcement
- `/announce_user_recording` - Upload and announce a recorded audio file (PUT/POST, `audio_data` multipart field)
- `/ls_speakers` - JSON array of discovered Sonos speaker names (sorted)
- `/announcement_history` - JSON array of the 10 most recent announcements
- `/svc_config` - JSON with internal config (HTTPS server URL)
- `/tts/*` - Cached TTS audio assets (served to Sonos speakers over HTTP)

## HTTPS

An HTTPS server is started alongside the normal HTTP server. HTTP routes `/zmw.css` and `/zmw.js` are mirrored to HTTPS. The microphone recording UI requires HTTPS because browsers require a secure context for `getUserMedia`. Sonos speakers fetch audio over HTTP (they cannot validate self-signed certificates).

## MQTT

**Topic:** `zmw_speaker_announce`

### Commands

#### `ls`

List available Sonos speakers. Response published on ls_reply

_No parameters._

#### `tts`

Convert text to speech and play on all Sonos speakers

| Param | Description |
|-------|-------------|
| `msg` | Text to announce |
| `lang` | (optional) Language code for TTS. Uses configured default if omitted |
| `vol` | (optional) Volume 0-100. Uses configured default if omitted |

#### `save_asset`

Copy a local audio file into the TTS asset cache so it can be served to speakers. Response published on save_asset_reply

| Param | Description |
|-------|-------------|
| `local_path` | Absolute path to the audio file on disk |

#### `play_asset`

Play an audio asset on all Sonos speakers. Exactly one source must be specified

| Param | Description |
|-------|-------------|
| `name` | (option 1) Filename of an asset already in the TTS cache |
| `local_path` | (option 2) Absolute path to a local file (will be copied to cache first) |
| `public_www` | (option 3) Public URL of an audio file |
| `vol` | (optional) Volume 0-100. Uses configured default if omitted |

#### `announcement_history`

Request recent announcement history. Response published on announcement_history_reply

_No parameters._

#### `get_mqtt_description`

Request MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `ls_reply`

Response to ls. Sorted list of Sonos speaker names

Payload: `['speaker_name_1', 'speaker_name_2']`

#### `tts_reply`

Published after a TTS announcement completes. Contains the generated asset paths

| Param | Description |
|-------|-------------|
| `local_path` | Filename of the generated TTS audio in the cache |
| `uri` | Public URL where the TTS audio is served |

#### `save_asset_reply`

Response to save_asset. Contains status and asset URI on success

| Param | Description |
|-------|-------------|
| `status` | 'ok' or 'error' |
| `asset` | (on success) Filename of the saved asset |
| `uri` | (on success) Public URL of the saved asset |
| `cause` | (on error) Error description |

#### `announcement_history_reply`

Response to announcement_history. List of recent announcements

Payload: `[{'timestamp': 'ISO timestamp', 'phrase': 'Announced text or marker', 'lang': 'Language code', 'volume': 'Volume used', 'uri': 'Audio URI played'}]`

#### `get_mqtt_description_reply`

Response to get_mqtt_description with this API description

(this object)

# ZmwSpeechToText

Offline speech-to-text service using faster-whisper. Transcribes audio from Telegram voice messages, HTTP uploads, or MQTT file-path requests, and publishes results back to MQTT. Optionally translates non-English audio to English in a single pass using Whisper's built-in translate task.

## Configuration

| Key | Description |
|-----|-------------|
| `stt.model_size` | Whisper model size (default: `tiny.en`). Options: `tiny`, `tiny.en`, `base`, `base.en`, `small`, `small.en`, `medium`, `medium.en`, `large-v2`, `large-v3` |
| `stt.compute_type` | Model precision (default: `int8`). Options: `int8`, `float16`, `float32` |
| `stt.local_files_only` | If `true`, only use already-downloaded models. Set to `false` on first run to download, then switch back to `true` |
| `stt.language` | Source language hint for Whisper (default: `en`). Set to `null` for auto-detection |
| `stt.task` | Whisper task (default: `translate`). Use `transcribe` to keep original language, `translate` to output English |
| `stt.beam_size` | Beam search width (default: `5`). Higher values are slower but may be more accurate |

## Dependencies

- `ZmwTelegram` -- Listens to `on_voice` announcements for incoming voice/audio messages. Received audio is transcribed and the result is published as a `transcription` announcement.

## WWW

- `/` -- Monitoring UI (served from `www/` directory)
- `POST /transcribe` -- Upload raw audio bytes, returns JSON `{source, file, text, confidence}`
- `GET /history` -- Last 20 transcription results as a JSON array

## Model Loading

The STT model is loaded in a background thread at startup. If loading fails (e.g., `local_files_only` is `true` but the model has not been downloaded), the service stays running but all transcription requests are rejected with a warning. To download the model for the first time, set `local_files_only` to `false`, restart the service, then optionally set it back to `true`.

## MQTT

**Topic:** `zmw_speech_to_text`

### Commands

#### `transcribe`

Transcribe an audio file at the given path

| Param | Description |
|-------|-------------|
| `wav_path` | (preferred) Path to a WAV file |
| `path` | (fallback) Path to any audio file |

#### `get_history`

Request transcription history. Response published on get_history_reply

_No parameters._

### Announcements

#### `transcription`

Published when a transcription completes (from any source: HTTP, MQTT, or Telegram voice)

| Param | Description |
|-------|-------------|
| `source` | Origin: 'http', 'mqtt', or 'telegram' |
| `file` | Path to audio file (null for HTTP uploads) |
| `text` | Transcribed text |
| `confidence` | {'language': 'Detected language code', 'language_prob': 'Language detection probability', 'avg_log_prob': 'Average log probability of segments', 'no_speech_prob': 'Probability of no speech in segments'} |

#### `get_history_reply`

Response to get_history. Array of recent transcription results (max 20)

Payload: `[{'source': 'Origin', 'file': 'Audio path', 'text': 'Transcribed text', 'confidence': 'Confidence metrics'}]`

#### `get_mqtt_description_reply`

Response to get_mqtt_description. Describes all MQTT commands and announcements for this service

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |

# ZmwSpotify

Spotify playback control service. Manages OAuth authentication with the Spotify API and provides playback controls (play/pause, stop, volume, track navigation) over MQTT. Exposes current playback state including track metadata, album art, and progress.

## Configuration

| Key | Description |
|-----|-------------|
| `client_id` | Spotify application client ID |
| `client_secret` | Spotify application client secret |
| `redirect_uri` | OAuth redirect URI (must match Spotify app settings) |
| `spotipy_cache` | File path for caching Spotify OAuth tokens |

## WWW

- `/` - Static monitoring UI (served from `www/` directory)
- `/status` - HTML status page showing authentication state, playback status, volume, and current track info
- `/reauth` - OAuth reauthorization page for when the Spotify token expires or is invalidated
- `/reauth/complete/<code>` - Completes the OAuth flow with an authorization code

## Token Management

The Spotify access token is refreshed automatically every 45 minutes (tokens are valid for 60 minutes). If authentication fails, the service continues running but playback commands will be silently ignored until reauthentication succeeds via the `/reauth` WWW endpoint.

## Playback Error Handling

All Spotify API calls are wrapped with automatic retry: if a 401 (token expired) is received, the token is refreshed and the call is retried once. Network errors are caught and logged without crashing the service.

## MQTT

**Topic:** `zmw_spotify`

### Commands

#### `publish_state`

Request current player state. Response published on 'state'

_No parameters._

#### `stop`

Stop playback

_No parameters._

#### `toggle_play`

Toggle play/pause

_No parameters._

#### `next_track`

Jump to next track

_No parameters._

#### `prev_track`

Jump to previous track

_No parameters._

#### `relative_jump_to_track`

Skip forward or backward N tracks

| Param | Description |
|-------|-------------|
| `value` | Number of tracks to skip (positive=forward, negative=backward) |

#### `set_volume`

Set playback volume

| Param | Description |
|-------|-------------|
| `value` | Volume level 0-100 |

#### `get_status`

Request full player state as JSON. Response published on get_status_reply

_No parameters._

#### `get_mqtt_description`

Request MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `state`

Current player state (response to publish_state)

| Param | Description |
|-------|-------------|
| `is_authenticated` | bool |
| `is_playing` | bool |
| `volume` | int or null |
| `media_info` | dict with title, artist, album_name, album_link, icon, duration, current_time, track_count, current_track, context (or null) |

#### `get_status_reply`

Full player state as JSON (response to get_status)

| Param | Description |
|-------|-------------|
| `is_authenticated` | bool |
| `is_playing` | bool |
| `volume` | int or null |
| `media_info` | dict with title, artist, album_name, etc. (or null) |
| `reauth_url` | string (only when not authenticated) |

#### `get_mqtt_description_reply`

MQTT API description (response to get_mqtt_description)

The get_mqtt_description() dict itself

# ZmwTelegram

MQTT-to-Telegram bridge for bidirectional messaging. Runs a long-polling Telegram bot that relays commands and voice messages over MQTT, and allows other services to send text or photos through Telegram.

## Configuration

| Key | Description |
|-----|-------------|
| `tok` | Telegram bot API token |
| `bot_name` | Display name for the bot |
| `bcast_chat_id` | Default chat ID for outgoing messages |
| `accepted_chat_ids` | List of chat IDs the bot will respond to |
| `topic_map_chat` | Map of topic names to chat IDs for routing messages to specific chats |
| `short_poll_interval_secs` | Polling interval when active |
| `long_poll_interval_secs` | Polling interval when idle |
| `msg_history_len` | Number of messages to keep in history |
| `voice_download_path` | Directory for downloaded voice/audio files |

## WWW

- `/` - React monitoring UI (served from `www/` directory)
- `/messages` - JSON array of message history (sent and received)

## Rate Limiting

Outgoing messages are rate-limited to 3 messages per 60 seconds. If the limit is exceeded, further messages are dropped and the cooldown resets with each attempt (i.e. the window only expires after 60 seconds of silence).

## Voice Processing

Voice and audio messages are downloaded and transcoded to WAV (PCM 16-bit, 16kHz mono) for STT compatibility. Constraints:
- Messages longer than 60 seconds are dropped
- Transcoded WAV files larger than 5MB are discarded
- At most 30 voice files are kept on disk; oldest are cleaned up automatically
- Supported input formats: OGG, MP3, M4A, WAV, FLAC, AAC

## Built-in Telegram Commands

- `/ping` - Replies with PONG, or echoes back arguments
- `/stfu <minutes>` - Suppresses all outgoing messages for N minutes (default 10)

## MQTT

**Topic:** `zmw_telegram`

### Commands

#### `register_command`

Register a Telegram bot command that will be relayed over MQTT when invoked

| Param | Description |
|-------|-------------|
| `cmd` | Command name (without /) |
| `descr` | Help text for the command |

#### `send_photo`

Send a photo to a Telegram chat

| Param | Description |
|-------|-------------|
| `path` | Local file path to the image |
| `msg` | (optional) Caption |
| `topic` | (optional) Route to a specific chat via topic_map_chat |

#### `send_text`

Send a text message to a Telegram chat

| Param | Description |
|-------|-------------|
| `msg` | Message text |
| `topic` | (optional) Route to a specific chat via topic_map_chat |

#### `get_history`

Request message history. Response published on get_history_reply

_No parameters._

### Announcements

#### `on_command/<cmd>`

Published when a registered Telegram command is received

| Param | Description |
|-------|-------------|
| `cmd` | The command name |
| `cmd_args` | List of arguments |
| `from` | Sender info |
| `chat` | Chat info |

#### `on_voice`

Published when a voice/audio message is received (max 60s)

| Param | Description |
|-------|-------------|
| `path` | Original audio file path |
| `wav_path` | Transcoded WAV path (null if failed) |
| `from_id` | Sender ID |
| `from_name` | Sender name |
| `chat_id` | Chat ID |
| `duration` | Duration in seconds |
| `original_mime_type` | MIME type of original audio |

#### `get_history_reply`

Response to get_history. List of message objects

Payload: `[{'timestamp': 'ISO timestamp', 'direction': 'sent|received', 'message': 'Message content'}]`

# ZmwWhatsapp

MQTT-to-WhatsApp bridge for sending photos and messages via the WhatsApp Business Cloud API. Uses Facebook's Graph API to upload media and send template-based messages to configured phone numbers.

## Configuration

| Key | Description |
|-----|-------------|
| `tok` | WhatsApp Business API permanent access token |
| `from_number` | Origin phone number ID (from the Facebook developer dashboard) |
| `notify_targets` | List of target phone numbers to send messages to |
| `msg_history_len` | Number of message events to keep in history |

## WWW

- `/` - Monitoring UI (served from `www/` directory)
- `/messages` - JSON array of message history events

## Rate Limiting

Outgoing messages are rate-limited to 3 messages per 60 seconds. If the limit is exceeded, further messages are dropped and the cooldown resets with each attempt (i.e. the window only expires after 60 seconds of silence).

## Notes

- Text messages (`send_text`) are not yet implemented; the command is accepted but logs a warning and records the attempt.
- Photos are sent via WhatsApp template messages (`sample_purchase_feedback` by default), because the API does not allow sending standalone images to users who haven't recently interacted with the bot.
- Considerable setup is required on the Facebook developer dashboard (developer account, business app, WhatsApp integration, phone number enrollment, permanent token). See `whatsapp.py` for detailed setup instructions.

## MQTT

**Topic:** `zmw_whatsapp`

### Commands

#### `send_photo`

Send a photo to all WhatsApp notify targets via a template message

| Param | Description |
|-------|-------------|
| `path` | Local file path to the image |
| `msg` | (optional) Caption text |

#### `send_text`

Send a text message to all WhatsApp notify targets (not yet implemented)

| Param | Description |
|-------|-------------|
| `msg` | Message text |

#### `get_history`

Request message history. Response published on get_history_reply

_No parameters._

### Announcements

#### `get_history_reply`

Response to get_history. List of message event objects

Payload: `[{'timestamp': 'ISO timestamp', 'direction': 'sent', 'type': 'photo|text', '...': 'Additional details depending on type'}]`
