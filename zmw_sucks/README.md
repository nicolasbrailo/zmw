# ZmwSucks

Local-only Roomba control. Talks to the robot's own MQTT server (TLS, port 8883) via
[roombapy](https://github.com/pschmitt/roombapy): no iRobot cloud involved.

Connects to each robot, exposes its state, stats, settings and schedule, and start/pause/dock/find commands. `find`
(the robot plays its locate chime, without moving) is handy as an end-to-end test.

## Monitoring

Problems are sent over Telegram (via ZmwTelegram), and shown as service alerts (`/svc_alerts`) while they last:

- Scheduled runs: 2 minutes after a scheduled run was due, check the robot is cleaning. For the robot's own
  schedule, uses the robot's timezone, and its last known schedule if it's offline. The alert clears when the robot
  starts a mission. Works the same for schedules in the service config (see Schedule).
- Missions: every 5 minutes, check running robots. Reports if a robot gets stuck, reports an error, has a full bin,
  or disconnects. Each problem is reported once, unless it clears and comes back. When a mission ends, its result
  (completed, failed, cancelled) comes from the robot's own mission counters.

Notifications for scheduled runs (missions the robot reports as started by its schedule, or seen starting at a
scheduled time) are controlled by these top level config keys:

- `notify_on_schedule_success` (default false): message when a scheduled run completes
- `notify_on_schedule_failure` (default true): message when a scheduled run doesn't start, has a problem, fails or
  is cancelled. Service alerts are kept either way.

Missions not started by the schedule always notify problems and failures, but not completion.
- Service alerts also include: bin full, errors, stuck, a rejected password, robots not found on the network, and
  robots not connected for 30 minutes. A robot that is not found is only logged the first time.

## History

The last runs of each robot (`history_len` in config, default 20) are kept, and survive service restarts (in the
runtime state cache). Shown in the UI, and available on `/get_history` and the `get_history` MQTT command. Each run
has its start and end time, whether it was scheduled, who started it, duration and area cleaned, problems seen
during the mission, and its result:

- `running`, then `ok`, `failed`, `cancelled` (from the robot's mission counters, see Monitoring), or `unknown` if
  the robot didn't count it, or the service didn't see it end (eg it was restarting)
- `missed`: a scheduled run that didn't start (or the robot wasn't connected, so it can't be told)

Duration and area are as last seen while running (missions are checked every 5 minutes), since the robot resets
them when the mission ends.

## Schedule

A robot can follow its own schedule (set in the iRobot app), or one in the service config (`schedule`, see
Configuration). With the service schedule, the service sends `start` when a run is due (or up to 2 minutes late, eg
if the service was restarting), unless the robot is already cleaning. Times are local to the service. These runs
are monitored and notified like the robot's own scheduled runs.

Only one schedule is followed: if a robot has its own (any enabled entry, even if on hold), the service schedule is
ignored, an error is logged when the service first sees the robot, and it shows as a service alert until one of
them is removed. If the robot has no
schedule of its own but was never seen connected, the service schedule is followed.

## Configuration

`config.json` (see `config.template.json`) has the notification settings (see Monitoring), `history_len` (see
History), and a `roombas` list, one entry per robot:

- `alias`: unique name for the robot, used in MQTT topics (`zmw_sucks/<alias>/state`) and endpoints
- `blid`: robot ID
- `password`: the robot's local MQTT password (not the iRobot account password)
- `discovery_mechanism` (optional): how to find the robot's IP. Defaults to `fixed_ip` if `ip` is set, else
  `broadcast`:
  - `broadcast`: find the robot by BLID with a UDP broadcast. Only works if the robot is on the same subnet as the
    service
  - `unifi`: ask ZmwUnifiClientmon for the IP of the client with hostname `Roomba-<blid>` (or `iRobot-<blid>`),
    then check the robot answers discovery there. Works across subnets (eg a robot in an IoT VLAN), as long as the
    service can reach it
  - `fixed_ip`: always connect to `ip`, never rediscover
- `ip`: fixed robot IP. Required with (and only allowed with) `discovery_mechanism` `fixed_ip`
- `schedule` (optional): runs for the service to start, as a list of `{"day": "Mon", "time": "10:00"}`. Days are
  `Sun` to `Sat`, times are 24h and local to the service. Ignored if the robot has its own schedule (see Schedule)
- `ignore` (optional): if true, this entry is skipped at startup (eg to keep config for a robot not in use yet)

Robots are discovered at startup, and again if they stay disconnected for 5 minutes (eg if DHCP gave them a new
IP). Robots that can't be found or connected to are retried every 30 secs, and show as not connected.

The BLID is the `robotid` the robot reports on discovery (UDP 5678, `irobotmcs`). The password can be fetched
locally with `roombapy discover <ip>`, after holding the robot's HOME button for ~2 seconds while docked. Some
firmwares only give it out from the cloud: `make get_cloud_password EMAIL=<iRobot account email>` gets it once,
after that the cloud isn't needed.

## Dependencies

roombapy is vendored (a copy, not a submodule) in `../zext_libs/roombapy`. `VENDORED_FROM` says which commit.
To update it to whatever is on the upstream default branch: `make roombapy_dep_update`, then `make rebuild_deps`.

## WWW Endpoints

- `/` - React UI with each robot's status, stats and Start/Pause/Dock/Find buttons (served from `www/` directory)
- `GET /get_history` - Map of robot alias to its last runs, newest first (see History)
- `GET /get_state` - Map of robot alias to current state: status, current mission, lifetime stats, Wi-Fi signal and
  position (if the robot supports position requests; only polled while away from the dock)
- `PUT /set_setting/<alias>/<setting>/<value>` - Change a setting: `passes` (auto/one/two), `bin_pause`
  (true/false), `child_lock` (true/false)
- `GET /get_raw_state/<alias>` - Debug: everything the robot reports, unparsed (fields vary by model and firmware)
- `PUT /start/<alias>` - Start cleaning (or resume, if paused)
- `PUT /pause/<alias>` - Pause cleaning
- `PUT /dock/<alias>` - Stop cleaning, and go back to the dock
- `PUT /find/<alias>` - Make a robot play its locate chime

## MQTT

**Topic:** `zmw_sucks`

### Commands

#### `get_state`

Current state of all robots. Response on get_state_reply

_No parameters._

#### `get_history`

Last runs of each robot, newest first. Response on get_history_reply

_No parameters._

#### `start`

Start cleaning (or resume, if paused). Response on start_reply

| Param | Description |
|-------|-------------|
| `alias` | Robot alias, as in config |

#### `pause`

Pause cleaning. Response on pause_reply

| Param | Description |
|-------|-------------|
| `alias` | Robot alias, as in config |

#### `dock`

Stop cleaning, and go back to the dock. Response on dock_reply

| Param | Description |
|-------|-------------|
| `alias` | Robot alias, as in config |

#### `find`

Play the locate chime, without moving. Response on find_reply

| Param | Description |
|-------|-------------|
| `alias` | Robot alias, as in config |

#### `set_setting`

Change a robot setting. Response on set_setting_reply

| Param | Description |
|-------|-------------|
| `alias` | Robot alias, as in config |
| `setting` | None |
| `value` | None |

#### `get_raw_state`

Debug: everything a robot reports, unparsed. Response on get_raw_state_reply

| Param | Description |
|-------|-------------|
| `alias` | Robot alias, as in config |

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `<alias>/state`

Published when a robot's state changes

| Param | Description |
|-------|-------------|
| `alias` | Robot alias, as in config |
| `connected` | Local connection to robot is up. If false, no other fields are present |
| `ip` | Robot IP (discovered, unless fixed in config) |
| `robot_name` | Name the robot reports for itself |
| `state` | Derived mission state (eg 'Charging', 'Running') |
| `phase` | Raw cleanMissionStatus phase |
| `battery_pct` | Battery % |
| `bin_full` | Bin is full |
| `error_code` | Error code, or null |
| `error` | Error message, or null |
| `mission` | {'id': 'Mission ID', 'cycle': "Mission type (eg 'clean', 'none')", 'initiator': "Who started it (eg 'localApp', 'schedule', 'rmtApp')", 'start_time': 'Mission start, epoch secs', 'minutes': 'Mission duration so far', 'sqft': 'Area cleaned so far', 'recharge_minutes': 'Minutes until recharge completes, mid mission', 'expire_minutes': 'Minutes until the mission is abandoned, if paused'} |
| `lifetime` | {'runtime_hours': 'Total runtime, hours part', 'runtime_minutes': 'Total runtime, minutes part', 'sqft': 'Total area cleaned', 'missions': 'Missions started', 'missions_ok': 'Missions completed', 'missions_failed': 'Missions failed', 'missions_cancelled': 'Missions cancelled', 'avg_mission_minutes': 'Average mission duration', 'stuck_count': 'Times the robot got stuck'} |
| `battery` | {'charge_cycles': 'Battery charge cycles', 'est_capacity_mah': 'Estimated battery capacity, mAh', 'manufacture_date': 'Battery manufacture date'} |
| `settings` | {'passes': 'auto/one/two', 'bin_pause': 'Stop cleaning when the bin is full', 'child_lock': 'Robot buttons disabled'} |
| `schedule` | {'paused': 'Schedule is on hold', 'timezone': 'Robot timezone, schedule times are local to it', 'entries': [{'enabled': 'Entry is active', 'days': ['Mon', '...'], 'day_nums': 'Days, 0 = Sunday', 'hour': 'Start hour', 'min': 'Start minute', 'command': "Usually 'start'"}]} |
| `service_schedule` | Schedule from the service config, run by the service, or null. Same format as schedule (times local to the service), plus 'ignored': true if the robot has its own schedule, so this one isn't run |
| `wifi` | {'rssi': 'Signal strength, dBm', 'snr': 'Signal to noise ratio'} |
| `position_supported` | Robot answers position requests (null until known) |
| `position` | Last known position, or null: {x_m, y_m, theta_rad}, origin at the dock |

#### `get_raw_state_reply`

Everything the robot reports

| Param | Description |
|-------|-------------|
| `alias` | Robot alias |
| `connected` | Connection is up |
| `reported` | {} |

#### `get_state_reply`

Map of robot alias to state

See `<alias>/state`

#### `get_history_reply`

Map of robot alias to its last runs (missions, and scheduled runs that didn't start), newest first

| Param | Description |
|-------|-------------|
| `<alias>` | [{'start': 'Start, epoch secs (for missed runs, when the miss was detected)', 'end': 'End, epoch secs, or null while running', 'result': None, 'scheduled': "Started by a schedule (the robot's own or the service's)", 'scheduled_time': 'Scheduled start (HH:MM), if known', 'initiator': "Who started it, as reported by the robot (eg 'localApp', 'schedule')", 'mission_id': "Robot's mission ID", 'minutes': 'Mission duration, as last seen while running', 'sqft': 'Area cleaned, as last seen while running', 'problems': "Problems seen during the mission (eg 'is stuck', 'disconnected')", 'details': 'Robot state when it ended (if not ok), or why the run was missed'}] |

#### `start_reply`

start sent to robot (or failed to)

| Param | Description |
|-------|-------------|
| `alias` | Robot alias |
| `status` | ok/not_connected/unknown_device |

#### `pause_reply`

pause sent to robot (or failed to)

| Param | Description |
|-------|-------------|
| `alias` | Robot alias |
| `status` | ok/not_connected/unknown_device |

#### `dock_reply`

dock sent to robot (or failed to)

| Param | Description |
|-------|-------------|
| `alias` | Robot alias |
| `status` | ok/not_connected/unknown_device |

#### `find_reply`

find sent to robot (or failed to)

| Param | Description |
|-------|-------------|
| `alias` | Robot alias |
| `status` | ok/not_connected/unknown_device |

#### `set_setting_reply`

Setting sent to robot (or failed to)

| Param | Description |
|-------|-------------|
| `alias` | Robot alias |
| `status` | ok/not_connected/unknown_device/unknown_setting/bad_value |

#### `get_mqtt_description_reply`

Service description

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |
