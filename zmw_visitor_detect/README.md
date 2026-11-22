# ZmwVisitorDetect

Detects people at the doorbell and identifies them, discovering frequent visitors on its own (no enrolment).
A motion or ring event from ZmwReolinkCams opens a session on the camera's RTSP main stream; the session
publishes at most one event per person, and stops when the scene is idle or still. All inference is local, on
CPU (onnxruntime).

Models, thresholds and the evidence behind them were chosen in a separate sandbox (`~/src/visitordetect`, see
its `ARCH.md` and `CLAUDE.md`).

## Pipeline

Per frame (4 fps, newest frame wins), cheapest checks first:

1. Day/night: IR night frames are greyscale. Night only ever reports people: IR faces never matched reliably.
2. Motion delta on a 160x120 thumbnail (day only): skips the face detector when nothing changed since the last
   analysed frame, and the person detector when nothing changed since its last run.
3. Person detector (YOLOX-m + YOLO11m, merged) every 2 s by day, 4 s by night -> `on_person_detected`. Boxes
   shorter than `person_min_height_px` (background passers-by) are ignored. With `person_detection: "first"`
   (default) it stops once a person was reported; `"always"` keeps checking (a still person keeps the session
   open); `"off"` never runs it (people are then only reported through their faces, so never at night).
4. Face stage (day): SCRFD on the full frame -> face tracker -> quality gate (confidence, size, frontal) ->
   ArcFace on faces that pass the gate. Once a track has 2 good faces it is decided: same person as earlier
   in the session (nothing), a known visitor (`on_face_identified`) or unknown (`on_face_detected`).

After a session, unknown faces are clustered; a face seen in 3 visits on 2 different days becomes "Visitor N"
(`on_new_frequent_visitor`). Name visitors with `visitor_names` in the config.

## Configuration

| Key | Description |
|-----|-------------|
| `cam_aliases` | Cameras (`cam_alias` in ZmwReolinkCams) to watch, default `["doorbell"]` |
| `models_dir` | ONNX models, default `./models` (`make download_models`) |
| `data_dir` | Identity store (SQLite + face crops) and session decision logs, default `./visitor_data` |
| `visitor_names` | `{"visitor_3": "Name"}`: display names for discovered visitors |
| `person_detection` | `"always"`, `"first"` (default) or `"off"`: when to run the person detector (see Pipeline) |
| `face_gate` | Quality gate limits, eg `{"max_yaw": 0.3}` (others keep their defaults, see `face_gate.py`) |
| `inference` | `"cpu"` (default, onnxruntime) or `"gpu"` (OpenVINO on the Intel GPU, ~2.5x faster, same results). No fallback: if the chosen backend can't run, the service refuses to start. GPU setup: `make setup_gpu`, `make check_gpu` |
| `hw_decode` | `"vaapi"` (default: GPU video decoding, CPU fallback) or `"off"`. The Status page shows which is in use and why. Set the GPU up with `make setup_gpu`, restart, verify with `make check_gpu` |
| `person_min_height_px` | Ignore person boxes shorter than this, default 300 (on the 1920px tall main stream) |

Every threshold can be overridden too (`visitor_config.py` has the list and the defaults); changing one never
requires discarding stored data. Notifications (Telegram, announcements) are left to consumers of the events.

## WWW

- `/`: UI. Sessions (timeline and decision log: why each session flagged or didn't), Visitors (faces; split,
  merge, remove a face, delete), Unknown faces (groups waiting for promotion; reset a group), Status.
- `/status`, `/sessions`, `/session/<id>`, `/visitors`, `/unknown`: JSON. `PUT /admin/<op>`: admin actions.
- `/data/<path>`: face crops and session crops.

## Testing with a recorded clip

`make inject_clip` plays a recorded clip as the doorbell's live stream, in real time (the `inject_clip` command;
also a form in the UI's Status tab). It's a real session: it fires events and feeds the identity store. The clip
must be inside one of the config's `allowed_paths` (eg the recordings dir); nothing is allowed if it's unset.

## MQTT

**Topic:** `zmw_visitor_detect`

### Commands

#### `inject_clip`

Test the pipeline end to end: play a recorded clip as if it were the camera's live stream. It's a real session: it fires events and feeds the identity store. Response on inject_clip_reply

| Param | Description |
|-------|-------------|
| `cam_alias` | Camera to impersonate |
| `path` | Absolute path to a clip on the server |

### Announcements

#### `on_person_detected`

First person seen in a session (from the person detector, or from a face if that came first). Once per session: faceless people can't be told apart

| Param | Description |
|-------|-------------|
| `event` | on_person_detected |
| `cam_alias` | Camera |
| `session_id` | Session id |
| `timestamp` | float epoch |
| `t` | Seconds into the session |
| `day_night` | day or night |
| `via` | person_detector or face |
| `conf` | Person confidence (null if via face) |
| `person_count` | People in that frame |
| `crop_path` | Person crop (local path) |

#### `on_face_detected`

A face good enough to identify, of someone not known (yet). Once per person per session

| Param | Description |
|-------|-------------|
| `event` | on_face_detected |
| `cam_alias` | Camera |
| `session_id` | Session id |
| `timestamp` | float epoch |
| `t` | Seconds into the session |
| `day_night` | day |
| `track_id` | Face track in the session |
| `gated_faces` | Faces used |
| `closest` | Closest known visitor id or null |
| `closest_sim` | Its similarity |
| `face_crop_path` | Aligned 112px face |
| `context_crop_path` | Crop around the face |

#### `on_face_identified`

A known visitor's face. Once per visitor per session

| Param | Description |
|-------|-------------|
| `event` | on_face_identified |
| `cam_alias` | Camera |
| `session_id` | Session id |
| `timestamp` | float epoch |
| `t` | Seconds into the session |
| `day_night` | day |
| `visitor_id` | Stable id, eg visitor_3 |
| `name` | Display name (config visitor_names) |
| `sim` | Similarity |
| `upgraded` | True if first reported as on_face_detected |
| `track_id` | Face track in the session |
| `gated_faces` | Faces used |
| `face_crop_path` | Aligned 112px face |
| `context_crop_path` | Crop around the face |

#### `on_new_frequent_visitor`

Discovery promoted a recurring unknown face to a visitor (after a session ends)

| Param | Description |
|-------|-------------|
| `event` | on_new_frequent_visitor |
| `cam_alias` | Camera |
| `session_id` | Session id |
| `timestamp` | float epoch |
| `visitor_id` | Stable id, eg visitor_3 |
| `name` | Display name |
| `visits` | Visits seen in |
| `days` | Days seen on |
| `face_crop_paths` | A few crops of this visitor |

#### `inject_clip_reply`

Response to inject_clip

| Param | Description |
|-------|-------------|
| `session_id` | Session started, or null |
| `error` | Why it wasn't started, or null |
