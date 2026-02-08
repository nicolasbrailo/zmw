# ZmwSpotify

Spotify playback control service. Manages OAuth authentication with the Spotify API and provides playback controls (play/pause, stop, volume, track navigation) over MQTT. Exposes current playback state including track metadata, album art, and progress.

## Configuration

| Key | Description |
|-----|-------------|
| `client_id` | Spotify application client ID |
| `client_secret` | Spotify application client secret |
| `redirect_uri` | OAuth redirect URI (must match Spotify app settings) |
| `spotipy_cache` | File path for caching Spotify OAuth tokens |

## WWW

- `/` - Static monitoring UI (served from `www/` directory)
- `/status` - HTML status page showing authentication state, playback status, volume, and current track info
- `/reauth` - OAuth reauthorization page for when the Spotify token expires or is invalidated
- `/reauth/complete/<code>` - Completes the OAuth flow with an authorization code

## Token Management

The Spotify access token is refreshed automatically every 45 minutes (tokens are valid for 60 minutes). If authentication fails, the service continues running but playback commands will be silently ignored until reauthentication succeeds via the `/reauth` WWW endpoint.

## Playback Error Handling

All Spotify API calls are wrapped with automatic retry: if a 401 (token expired) is received, the token is refreshed and the call is retried once. Network errors are caught and logged without crashing the service.

## MQTT

**Topic:** `zmw_spotify`

### Commands

#### `publish_state`

Request current player state. Response published on 'state'

_No parameters._

#### `stop`

Stop playback

_No parameters._

#### `toggle_play`

Toggle play/pause

_No parameters._

#### `next_track`

Jump to next track

_No parameters._

#### `prev_track`

Jump to previous track

_No parameters._

#### `relative_jump_to_track`

Skip forward or backward N tracks

| Param | Description |
|-------|-------------|
| `value` | Number of tracks to skip (positive=forward, negative=backward) |

#### `set_volume`

Set playback volume

| Param | Description |
|-------|-------------|
| `value` | Volume level 0-100 |

#### `get_status`

Request full player state as JSON. Response published on get_status_reply

_No parameters._

#### `get_mqtt_description`

Request MQTT API description. Response published on get_mqtt_description_reply

_No parameters._

### Announcements

#### `state`

Current player state (response to publish_state)

| Param | Description |
|-------|-------------|
| `is_authenticated` | bool |
| `is_playing` | bool |
| `volume` | int or null |
| `media_info` | dict with title, artist, album_name, album_link, icon, duration, current_time, track_count, current_track, context (or null) |

#### `get_status_reply`

Full player state as JSON (response to get_status)

| Param | Description |
|-------|-------------|
| `is_authenticated` | bool |
| `is_playing` | bool |
| `volume` | int or null |
| `media_info` | dict with title, artist, album_name, etc. (or null) |
| `reauth_url` | string (only when not authenticated) |

#### `get_mqtt_description_reply`

MQTT API description (response to get_mqtt_description)

The get_mqtt_description() dict itself
