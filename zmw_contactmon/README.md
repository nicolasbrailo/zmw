# ZmwContactMon

Contact sensor monitoring with timeout and curfew alerts. Monitors Zigbee contact sensors (doors, windows) and triggers configured actions when sensors change state, time out, or violate curfew.

## Configuration

| Key | Description |
|-----|-------------|
| `actions` | Dict of sensor_name -> event -> action mappings (see Actions below) |
| `curfew_hour` | (optional) Time in `HH:MM` format for daily curfew check |
| `chime_skip_default_secs` | Default duration (seconds) for skip-chimes requests |
| `chime_skip_max_secs` | Maximum allowed skip-chimes duration (seconds) |

### Actions

Each sensor in `actions` maps event types to action handlers:

**Events:** `open`, `close`, `timeout`, `curfew`
**Metadata:** `normal_state` (bool, required), `timeout_secs` (int, required if `timeout` event is defined)

**Action types:**

| Action | Description | Required params |
|--------|-------------|-----------------|
| `telegram` | Send a message via ZmwTelegram | `msg` |
| `whatsapp` | Send a message via ZmwWhatsapp | `msg` |
| `tts_announce` | Broadcast a TTS message via ZmwSpeakerAnnounce | `msg`, `lang` |
| `sound_asset_announce` | Play a sound file via ZmwSpeakerAnnounce | `local_path` or `public_www` |

## WWW

- `/` - React monitoring UI (served from `www/` directory)
- `/svc_state` - JSON: current sensor states, contact history, chime skip status
- `/skip_chimes` - Skip chime notifications for the default duration
- `/skip_chimes_with_timeout/<secs>` - Skip chime notifications for specified seconds
- `/enable_chimes` - Re-enable chime notifications immediately
- `/test_curfew` - Manually trigger a curfew check (debug)

## Curfew

When `curfew_hour` is configured, a daily check runs at that time. Any sensor in a non-normal state triggers its `curfew` action (if defined).

## Dependencies

- `ZmwSpeakerAnnounce` - for TTS and sound asset announcements
- `ZmwWhatsapp` - for WhatsApp notifications
- `ZmwTelegram` - for Telegram notifications

## MQTT

**Topic:** `zmw_contactmon`

### Commands

#### `skip_chimes`

Temporarily disable/silence/mute door chime notifications

| Param | Description |
|-------|-------------|
| `timeout?` | Seconds to skip chimes |

#### `enable_chimes`

Re-enable chimes immediately

_No parameters._

#### `publish_state`

Get open/closed state of monitored contact sensors. Response on publish_state_reply

_No parameters._

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `publish_state_reply`

Service state. Published after skip_chimes, enable_chimes, or publish_state

| Param | Description |
|-------|-------------|
| `sensors` | Dict of sensor_name -> {in_normal_state, contact, ...} |
| `history` | Recent contact state changes |
| `skipping_chimes` | true if chimes currently suppressed |
| `skipping_chimes_timeout_secs?` | Seconds until chimes re-enable |

#### `<sensor_name>/contact`

Published when a contact sensor changes state

| Param | Description |
|-------|-------------|
| `sensor` | Name |
| `contact` | Contact state |
| `prev_contact` | Previous contact state |
| `entering_non_normal` | True if entering non-default state (eg true if a door is open) |

#### `get_mqtt_description_reply`

Service definition

(this object)
