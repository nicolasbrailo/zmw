# ZmwHomeboard

An integration for my custom [Homeboard](https://nicolasbrailo.github.io/blog/projects_texts/24homeboard.html). Enables remote control of the Homeboard from the ZMW UI.

The Homeboard uses its custom MQTT service, not shared with ZMW. This service acts as a bridge between both. See the dbus-mqtt-bridge project in the homeboard for more details.



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

#### `set_svg_overlay`

Show an svg overlay in the Homeboards

| Param | Description |
|-------|-------------|
| `homeboard_id` | Name of the target homeboard |
| `timeout_secs` | How long it should be displayed (0 means forever) |
| `svg_file_path` | Path to the SVG file in the local filesystem |

#### `update_weather`

Recompute and push the overlay for all homeboards

_No parameters._
