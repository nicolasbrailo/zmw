# ZmwHomeboard

An integration for my custom [Homeboard](https://nicolasbrailo.github.io/blog/projects_texts/24homeboard.html). Enables remote control of the Homeboard from the ZMW UI.

The Homeboard uses its custom MQTT service, not shared with ZMW. This service acts as a bridge between both. See the dbus-mqtt-bridge project in the homeboard for more details.



## WWW UI

`www/app.js` shows every known homeboard and drives it through these endpoints,
which forward to the same commands as the MQTT interface:

| Endpoint | Method | Effect |
|----------|--------|--------|
| `/get_homeboards_state` | GET | everything the UI renders |
| `/cmd/<hb_id>/next`, `/cmd/<hb_id>/prev` | GET | move the slideshow |
| `/cmd/<hb_id>/force_on`, `/cmd/<hb_id>/force_off` | GET | screen on/off |
| `/cmd/<hb_id>/set_transition_time_secs/<secs>` | GET | seconds per picture, at least 1 |
| `/announce_all` | PUT `{"msg":..., "timeout_secs":...}` | one message on every homeboard; empty `msg` clears it |
| `/set_album_filter_all` | PUT `{"name":..., "exclude":..., "from_year":..., "to_year":...}` | one album filter on every homeboard; an empty object clears it |

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
