# ZmwDoorman

Doorbell event handler and notification coordinator. Orchestrates door events from a Reolink camera and contact sensor, playing announcement sounds, sending photos via WhatsApp/Telegram, and managing a door-open lighting scene.

![](README_screenshot.png)

## Configuration

| Key | Description |
|-----|-------------|
| `doorbell_announce_volume` | Volume level for speaker announcements on button press |
| `doorbell_announce_sound` | Sound file name (served from `www/` directory) to play on button press |
| `doorbell_contact_sensor` | Name of the Zigbee contact sensor on the door |
| `doorbell_cam_alias` | `cam_alias` of the doorbell camera, as configured in ZmwReolinkCams |
| `door_open_scene_thing_to_manage` | List of Zigbee light names to control in the door-open scene |
| `door_open_scene_timeout_secs` | Seconds before the door-open scene auto-expires |
| `latlon` | `[lat, lon]` for sunrise/sunset calculation (door-open scene only activates when dark) |
| `allowed_paths` | Dirs camera snapshots may come from; others are ignored |
| `relay_raw_cam_events` | Also send the camera's motion snapshot to WhatsApp ("Motion detected", at most one every 2 minutes) for any motion, person or not: to be notified of all motion, or as a fallback when ZmwVisitorDetect isn't running |
| `visitor_face_wait_secs` | After ZmwVisitorDetect reports a person, wait this long for a face before sending the person picture (see below) |
| `visitor_notify_repeat_secs` | Don't notify the same person again within this time |
| `visitor_notify_injected` | Also notify sessions from test clips injected into ZmwVisitorDetect |

## Service Dependencies

- **ZmwSpeakerAnnounce** -- plays doorbell chime sound
- **ZmwWhatsapp** -- sends visitor/doorbell photos via WhatsApp
- **ZmwTelegram** -- sends doorbell photos and new regular visitors via Telegram, handles `/door_snap` command
- **ZmwReolinkCams** -- provides camera snapshots, doorbell button press, and motion events
- **ZmwContactmon** -- provides door contact sensor open/close events and chime control
- **ZmwVisitorDetect** -- people and faces at the door, for the WhatsApp notifications

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
| `/get_visitor_detect_svc_url` | GET | JSON: URL of the ZmwVisitorDetect web UI |

## Door-Open Scene

When the door contact sensor reports the door opening and it is dark outside (based on sun position at the configured lat/lon), the service turns on a set of configured Zigbee lights. The scene auto-expires after a configurable timeout. If another service or user manually controls a managed light while the scene is active, that light is released from management. Motion events at the door extend the scene timer.

## Visitor notifications

People at the door are sent to WhatsApp from ZmwVisitorDetect's events, one message per visit, preferably with a
face (`visitor_notifier.py`). Camera motion alone is only sent with `relay_raw_cam_events`: most of it isn't a person.

- After `on_person_detected`, wait `visitor_face_wait_secs` for a face. The service waits at most this time until
  the visitor detection service can identify a face; if no face arrives on time, a generic "person detected" message
  is sent instead. Includes a picture. Defaults to 5s; experiments show that for a Reolink cam, 5s timeout catches a
  face 70% of the time, whereas 10s only improved that to 80%.
- At night ZmwVisitorDetect only reports people, so the person picture goes out at once.
- One follow-up per visit: a face arriving after the first message (late, a second person, or an unknown face
  identified later).
- The same person isn't notified again within `visitor_notify_repeat_secs`.
- Pictures are large crops ZmwVisitorDetect writes to the services' shared scratch dir (its
  `notification_img_dir`), which must be in ZmwWhatsapp's `allowed_paths`. If ZmwVisitorDetect is down, nothing
  is sent (its missing dependency is alerted).

Each message sent is recorded in the door history ("visitor" rows); its link opens that session in ZmwVisitorDetect's
UI (`index.html#session=<id>`), with the visitor's crops and why they were (or weren't) identified.

A newly discovered regular visitor (`on_new_frequent_visitor`) goes to Telegram, not WhatsApp: "New regular
visitor: Visitor 5, seen in 3 visits on 2 days", with one of their faces, so they can be named in
ZmwVisitorDetect's `visitor_names`.

The doorbell ring is separate: it still sends the camera snapshot ("RING!") to WhatsApp and Telegram.

## Telegram Integration

Registers a `/door_snap` command with ZmwTelegram. When invoked, requests a snapshot from the doorbell camera and sends it back over Telegram. Snap requests that take longer than 5 seconds are discarded.

## MQTT

**Topic:** `zmw_doorman`

### Commands

#### `get_stats`

List of events: doorbell presses, motion, door open, visitors notified. Response on get_stats_reply

_No parameters._

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `on_doorbell_ring`

Doorbell button pressed, sent at once; on_doorbell_pressed follows with a snapshot

| Param | Description |
|-------|-------------|
| `rtsp_urls` | Stream name (main, sub) -> RTSP URL with credentials; empty if the camera didn't report any |

#### `on_doorbell_pressed`

Doorbell button pressed, with a snapshot

| Param | Description |
|-------|-------------|
| `snap_path?` | Path to camera snapshot |

#### `on_motion_detected`

Motion detected by door camera

| Param | Description |
|-------|-------------|
| `snap_path?` | Path to camera snapshot |

#### `on_motion_cleared`

No motion at door (vacancy reported or timeout)

#### `on_door_opened`

Door contact sensor reports open

#### `on_door_closed`

Door contact sensor reports closed

#### `get_stats_reply`

Door stats

| Param | Description |
|-------|-------------|
| `doorbell_press_count_today` | int |
| `motion_detection_count_today` | int |
| `visitor_count_today` | int |
| `last_snap` | filename or null |
| `last_snap_time` | epoch or null |
| `history` | list of event records |
| `motion_in_progress` | bool |
| `door_open_in_progress` | bool |

#### `get_mqtt_description_reply`

Service interface

| Param | Description |
|-------|-------------|
| `commands` | ... |
| `announcements` | ... |
