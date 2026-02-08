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
