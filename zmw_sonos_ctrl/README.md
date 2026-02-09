# ZmwSonosCtrl

Manages Sonos speaker groups and audio source selection. Discovers Sonos speakers on the local network, creates speaker groups, and hijacks Spotify playback to Sonos via the SoCo library. Provides both a web UI and MQTT interface for playback control.

## Dependencies

- **ZmwSpotify** - Used to fetch the current Spotify playback context (playlist URI, track offset) before redirecting playback to Sonos speakers.

## Configuration

This service reads its configuration from the standard `cfg` dict. No service-specific keys are required beyond the base `ZmwMqttService` configuration. Speaker discovery happens automatically via SoCo's network scan.

The Spotify-to-Sonos URI conversion uses a hardcoded Sonos magic URI (`sid=9&flags=8232&sn=6`). If this stops working, play a Spotify playlist from the Sonos app and inspect the URIs reported by the `/get_sonos_play_uris` endpoint to extract the correct values.

## WWW

- `/` - React UI for speaker group management and playback control (served from `www/` directory)
- `/world_state` - JSON: full Sonos network state (speakers, groups, zones). Cached for 30 seconds.
- `/ls_speakers` - JSON: list of discovered speaker names
- `/get_sonos_play_uris` - JSON: map of speaker name to currently-playing URI
- `/get_spotify_context` - JSON: current Spotify playback context (fetched from ZmwSpotify)
- `/stop_all_playback` - PUT: stops all playback and resets speaker group state
- `/volume` - PUT: set volume for specific speakers (JSON body: `{"SpeakerName": 50, ...}`)
- `/volume_up` - PUT/GET: increase volume on the active speaker group
- `/volume_down` - PUT/GET: decrease volume on the active speaker group
- `/next_track` - PUT/GET: skip to next track
- `/prev_track` - PUT/GET: skip to previous track

### WebSocket endpoints

- `/spotify_hijack` - Send a JSON speaker config to initiate Spotify hijack with real-time status updates. Expected payload: `{"SpeakerName": {"vol": 50}, ...}`
- `/line_in_requested` - (unimplemented) Intended for line-in source switching

## Spotify Hijack Flow

1. Fetches current Spotify state from ZmwSpotify via MQTT
2. Extracts the playlist/album URI and current track offset
3. Discovers and resets the requested Sonos speakers
4. Creates a speaker group with the first speaker as coordinator
5. Sets volumes per the provided configuration
6. Attempts playback via SoCo ShareLink, then falls back to direct URI methods
7. Optionally seeks to the current track offset

## MQTT

**Topic:** `zmw_sonos_ctrl`

### Commands

#### `prev_track`

Prev track

_No parameters._

#### `next_track`

Next track

_No parameters._

#### `volume_up`

volume+

| Param | Description |
|-------|-------------|
| `vol?` | Step percentage, default 5 |

#### `volume_down`

volume-

| Param | Description |
|-------|-------------|
| `vol?` | Step percentage, default 5 |

#### `spotify_hijack`

Move Spotify playback to set of Sonos speakers

| Param | Description |
|-------|-------------|
| `<speaker_name>` | {'vol?': 'level (0-100)'} |

#### `spotify_hijack_or_toggle_play`

If playing, pause. If paused, resume. Otherwise, start a new Spotify hijack

| Param | Description |
|-------|-------------|
| `<speaker_name>` | {'vol?': 'level (0-100)'} |

#### `stop_all`

Stop playback, destroy groups

_No parameters._

#### `world_state`

Get Sonos network state. Response on world_state_reply

_No parameters._

#### `ls_speakers`

List of speaker names. Response on ls_speakers_reply

_No parameters._

#### `get_sonos_play_uris`

URIs playing on each speaker. Response on get_sonos_play_uris_reply

_No parameters._

#### `get_spotify_context`

Get Spotify context/state. Response on get_spotify_context_reply

_No parameters._

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `world_state_reply`

Network state

| Param | Description |
|-------|-------------|
| `speakers` | List of speaker state |
| `groups` | Map of coordinator name to member |
| `zones` | List of zone names |

#### `ls_speakers_reply`

speaker list

Payload: `['names']`

#### `get_sonos_play_uris_reply`

Currently playing

| Param | Description |
|-------|-------------|
| `<speaker_name>` | URI |

#### `get_spotify_context_reply`

Spotify info with context URI and current track

| Param | Description |
|-------|-------------|
| `media_info` | dict |

#### `get_mqtt_description_reply`

Service description

| Param | Description |
|-------|-------------|
| `commands` | ... |
| `announcements` | ... |
