# ZmwReolinkCams

Multi-camera Reolink service with motion detection, doorbell events, recording, and an NVR-like web interface. Connects to one or more Reolink cameras via webhook/ONVIF, broadcasts events over MQTT, and provides snapshot/recording controls.

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
