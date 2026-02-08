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
