# ZmwHomeboard

An integration for my custom [Homeboard](https://nicolasbrailo.github.io/blog/projects_texts/24homeboard.html). Enables remote control of the Homeboard from the ZMW UI.

The Homeboard uses its custom MQTT service, not shared with ZMW. This service acts as a bridge between both. See the dbus-mqtt-bridge project in the homeboard for more details.

## Homeboard topics

`homeboard_mqtt.py` talks to the homeboard broker. Every device (a homeboard,
or a Portal running AstroDock) publishes retained topics under its own prefix,
and this service reads:

| Topic | What |
|-------|------|
| `<prefix>/availability` | online/offline plus host info; also the last will, so it is the liveness signal. A prefix is only known once this arrives: the other topics are ignored for prefixes without it |
| `<prefix>/state` | the device's state record (below) |
| `<prefix>/state/displayed_photo` | metadata of the picture on screen |
| `<prefix>/doctor` | health telemetry from homeboard-doctor (not retained) |

Commands go out on `<prefix>/cmd/<service>/<command>`.

A homeboard that goes away leaves its retained records behind. Every night at
03:00 this service deletes them for homeboards that are offline and last
booted over 3 days ago, and for prefixes whose `availability` can't be parsed.

The state record is one JSON object, republished whole whenever something in
it changes:

```json
{
 "occupancy": {"occupied": true, "source": "presence"},
 "slideshow": {"active": true, "shown_in": "home", "night_cover": false,
               "album_filter": {"name": "", "exclude": "", "from_year": 0, "to_year": 0}},
 "screen": {"on": true, "since": 1790704918, "screensaver": false,
            "wanted": null, "wanted_reason": null},
 "errors": [{"source": "immich", "message": "..."}],
 "battery": {"level": 80, "status": "charging", "plugged": "ac", "health": "good",
             "technology": "Li-ion", "temperature_c": 31.0, "voltage_v": 4.1},
 "wifi_rssi": -60,
 "light_lux": 3,
 "app": {"version": "1.0", "version_code": 1, "started_at": 1790705028, "device_booted_at": 1790185365},
 "ts": 1790705031
}
```

Any value may be `null` where the device doesn't know it or it doesn't apply
(a homeboard has no battery), and devices add keys of their own, such as
`occupancy.distance_cm` from the homeboard's mmWave sensor. The UI shows the
ones it doesn't know in the "Device state" section rather than dropping them.
`ts` is when the record last changed, not a heartbeat, so an old one only means
a quiet device; `availability` says whether it's alive.

This service republishes some parts of it on the ZMW bus, for ZmwSensormon,
each under `zmw_homeboard/<prefix>/`:

| Subtopic | Payload |
|----------|---------|
| `occupancy` | the `occupancy` object, without its null values |
| `slideshow_active` | `slideshow.active`, a bool |
| `battery` | the `battery` object, without its null values; never sent by devices without a battery |
| `wifi_rssi` | `wifi_rssi`, a number |
| `light_lux` | `light_lux`, a number |

Each is sent only when that part changed, and not at all while it's null.

## WWW UI

`www/app.js` shows every known homeboard and drives it through these endpoints,
which forward to the same commands as the MQTT interface:

| Endpoint | Method | Effect |
|----------|--------|--------|
| `/get_homeboards_state` | GET | everything the UI renders (below) |
| `/cmd/<hb_id>/next`, `/cmd/<hb_id>/prev` | GET | move the slideshow |
| `/cmd/<hb_id>/force_on`, `/cmd/<hb_id>/force_off` | GET | screen on/off |
| `/cmd/<hb_id>/set_transition_time_secs/<secs>` | GET | seconds per picture, at least 1 |
| `/announce_all` | PUT `{"msg":..., "timeout_secs":...}` | one message on every homeboard; empty `msg` clears it |
| `/set_album_filter_all` | PUT `{"name":..., "exclude":..., "from_year":..., "to_year":...}` | one album filter on every homeboard; an empty object clears it |

`/get_homeboards_state` returns `{"homeboards": [...], "album_filter": ...}`.
Each homeboard has `id`, `state` (`online`/`offline`, from `availability`),
`device_state` (the state record exactly as the device published it, or null
before it publishes one), `displayed_photo`, `host_info` (the whole availability
record) and `doctor`. The top-level `album_filter` is the one this service last
sent, or null; what each device is actually running is in its
`device_state.slideshow.album_filter`.

Announcements go out with the `announce` command rather than the composed SVG
overlay (`_set_announce`), so they also reach devices with no SVG renderer, such
as a Portal running alauncher.

The album filter is global too: there is one filter for all homeboards, pushed
to each of them, and every field is optional. An absent field means "no
constraint of that kind" rather than "leave it as it was", so the whole filter
is replaced on each command and an empty payload is the only way back to
showing every album. Each homeboard persists the filter itself; this service
only remembers what it last asked for, so a restart here doesn't change what
they're showing.

This section sits above `## MQTT` on purpose: `scripts/update_readme_mqtt.py`
regenerates everything from that header to the end of the file.

## MQTT

**Topic:** `zmw_homeboard`

### Commands

#### `next`

Move slideshow to next picture

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |

#### `prev`

Move slideshow to previous picture

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |

#### `force_on`

Force slideshow on

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |

#### `force_off`

Force slideshow off

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |

#### `set_transition_time_secs`

Set slideshow transition time in seconds

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `secs` | Transition time in seconds (non-negative integer) |

#### `set_embed_qr`

Enable or disable embedded QR code on photos

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `enabled` | true/false |

#### `set_target_size`

Set target photo size in pixels

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `width` | Width in pixels (positive integer) |
| `height` | Height in pixels (positive integer) |

#### `announce`

Show an announcement text in the Homeboard overlay (empty msg clears)

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `timeout_secs` | How long to display, in seconds |
| `msg` | Text to display; empty clears the current announce |

#### `announce_audio`

Tell a homeboard that the speakers are playing an audio file

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `uri` | URL of the audio being played |
| `volume?` | Volume 0-100 the speakers were asked to use |
| `msg?` | Text being spoken, when the audio comes from a TTS request |

#### `doorbell_ring`

Tell a homeboard the doorbell rang (sent to all of them on every ring)

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `rtsp_urls?` | Stream name (main, sub) -> RTSP URL of the door camera |

#### `set_svg_overlay`

Show an svg overlay in the Homeboards

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `timeout_secs` | How long it should be displayed (0 means forever) |
| `svg_file_path` | Path to the SVG file in the local filesystem |

#### `set_album_filter`

Pick which albums every homeboard may show pictures from; an empty request clears the filter and brings back all albums

| Param | Description |
|-------|-------------|
| `name` | Comma-separated glob patterns (*, ?) matched against the whole album name, case-insensitive; empty means every album |
| `exclude` | Same syntax as name, for albums to drop; wins over name |
| `from_year` | Only albums holding pictures from this year onwards (0 = no bound) |
| `to_year` | Only albums holding pictures up to this year (0 = no bound) |

#### `update_weather`

Recompute and push the overlay for all homeboards

_No parameters._
