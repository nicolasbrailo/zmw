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

#### `stop`

Stop playback

_No parameters._

#### `toggle_play`

Toggle play/pause

_No parameters._

#### `next_track`

Goto next

_No parameters._

#### `prev_track`

Goto prev

_No parameters._

#### `relative_jump_to_track`

Skip/back N tracks

| Param | Description |
|-------|-------------|
| `value` | Num of tracks to skip (positive=next, negative=back) |

#### `set_volume`

Volume

| Param | Description |
|-------|-------------|
| `value` | Level 0-100 |

#### `get_status`

Get state. Response on get_status_reply

_No parameters._

#### `get_mqtt_description`

MQTT API description. Response on get_mqtt_description_reply

_No parameters._

### Announcements

#### `get_status_reply`

Player state as JSON

| Param | Description |
|-------|-------------|
| `is_authenticated` | bool |
| `is_playing` | bool |
| `volume` | int or null |
| `media_info?` | dict with title, artist, album_name, etc. |
| `reauth_url` | url (when not authenticated) |

#### `get_mqtt_description_reply`

MQTT API description

The get_mqtt_description() dict itself
