# ZmwDoorman

Doorbell event handler and notification coordinator. Orchestrates door events from a Reolink camera and contact sensor, playing announcement sounds, sending photos via WhatsApp/Telegram, and managing a door-open lighting scene.

![](README_screenshot.png)

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
