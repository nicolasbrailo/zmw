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
