# ZmwVisitorDetect

Visitor detection and identification from doorbell camera snapshots. Detects persons using MobileNet-SSD, identifies faces using OpenFace embeddings, and auto-learns new visitors after repeated sightings. All inference runs on CPU via OpenCV DNN.

## Configuration

| Key | Description |
|-----|-------------|
| `doorbell_cam_host` | IP/hostname of the doorbell camera to monitor |
| `detection_cooldown_secs` | (optional) Per-person announcement cooldown, default 300 |
| `sighting_dedup_gap_secs` | (optional) Min gap between sightings to count as a new sighting, default 1800 |
| `models_dir` | (optional) Path to DNN model files, default `./models` |
| `detection_crops_dir` | (optional) Path to save person crops, default `./detection_crops` |
| `max_crops` | (optional) Max crop files to keep before rotating old ones, default 200 |

## Recognition Lifecycle

1. **person_no_face_detected** — person body found but no face in the crop
2. **new_face_detected** — face found but not yet seen enough times to be a visitor
3. **new_visitor_recognized** — face just crossed the sighting threshold, assigned a name ("Person N")
4. **visitor_recognized** — previously named visitor seen again

Sightings only increment if `sighting_dedup_gap_secs` has passed since the last sighting, preventing a person standing by the camera from being auto-promoted by rapid-fire motion events.

## WWW

- `/` - React detection history UI (served from `www/` directory)
- `/detections` - JSON: last 20 detection events
- `/crops/<filename>` - Served crop images

## Announcements

- **new_visitor_recognized** — sends photo to Telegram: "New visitor recorded: {name}"
- **visitor_recognized** — TTS via SpeakerAnnounce: "{name} is at the door"

Doorbell press always announces. Motion events respect `detection_cooldown_secs` per person.

## Models

Run `make download_models` to fetch the required DNN models (~64MB):

- `MobileNetSSD_deploy` — person detection (PASCAL VOC)
- `res10_300x300_ssd_iter_140000` — face detection
- `nn4.small2.v1.t7` — OpenFace 128-d face embeddings

## Dependencies

- `ZmwReolinkCams` - doorbell camera events (doorbell press, motion detection)
- `ZmwSpeakerAnnounce` - TTS announcements for known visitors
- `ZmwTelegram` - photo notifications for new visitors

## MQTT

**Topic:** `zmw_visitor_detect`

### Commands

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `on_detection`

Visitor detection event

| Param | Description |
|-------|-------------|
| `timestamp` | float epoch |
| `event` | new_face_detected | new_visitor_recognized | visitor_recognized | person_no_face_detected |
| `name` | Person name or null |
| `sightings` | int or null |
| `person_confidence` | float |
| `bbox` | [x1, y1, x2, y2] |
| `snap_path` | Source image path |
| `crop_path` | Cropped person image path |

#### `get_mqtt_description_reply`

Service interface

| Param | Description |
|-------|-------------|
| `commands` | ... |
| `announcements` | ... |
