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

Skip to the previous track on the active speaker group

_No parameters._

#### `next_track`

Skip to the next track on the active speaker group

_No parameters._

#### `volume_up`

Increase volume on the active speaker group

| Param | Description |
|-------|-------------|
| `vol` | (optional) Volume step percentage, default 5 |

#### `volume_down`

Decrease volume on the active speaker group

| Param | Description |
|-------|-------------|
| `vol` | (optional) Volume step percentage, default 5 |

#### `spotify_hijack`

Hijack Spotify playback to a set of Sonos speakers

| Param | Description |
|-------|-------------|
| `<speaker_name>` | {'vol': 'Volume level (0-100)'} |

#### `spotify_hijack_or_toggle_play`

If playing, pause. If paused, resume. Otherwise, start a new Spotify hijack

| Param | Description |
|-------|-------------|
| `<speaker_name>` | {'vol': 'Volume level (0-100)'} |

#### `stop_all`

Stop all playback and reset Sonos speaker states

_No parameters._

#### `world_state`

Request full Sonos network state. Response published on world_state_reply

_No parameters._

#### `ls_speakers`

Request list of discovered speaker names. Response published on ls_speakers_reply

_No parameters._

#### `get_sonos_play_uris`

Request URIs currently playing on all speakers. Response published on get_sonos_play_uris_reply

_No parameters._

#### `get_spotify_context`

Request current Spotify context/state. Response published on get_spotify_context_reply

_No parameters._

#### `get_mqtt_description`

Request MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `world_state_reply`

Response to world_state command

| Param | Description |
|-------|-------------|
| `speakers` | List of speaker state dicts |
| `groups` | Map of coordinator name to member names |
| `zones` | List of zone names |

#### `ls_speakers_reply`

Response to ls_speakers command

Payload: `['List of speaker name strings']`

#### `get_sonos_play_uris_reply`

Response to get_sonos_play_uris command

| Param | Description |
|-------|-------------|
| `<speaker_name>` | URI string currently playing |

#### `get_spotify_context_reply`

Response to get_spotify_context command

| Param | Description |
|-------|-------------|
| `media_info` | Spotify media info dict including context URI and current track |

#### `get_mqtt_description_reply`

Response to get_mqtt_description command

| Param | Description |
|-------|-------------|
| `commands` | ... |
| `announcements` | ... |
