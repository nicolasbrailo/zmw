# ZmwSpeakerAnnounce

Sonos speaker announcement service with TTS, pre-recorded asset playback, and live microphone recording support. Announcements are broadcast to all discovered Sonos speakers on the network.

![](README_screenshot.png)

## Modes

- **TTS**: Send a text phrase to be converted to speech and played on all speakers. Multiple languages are supported via the configured TTS engine.
- **Asset playback**: Play a pre-existing audio file by name (from the asset cache), by local file path (copied to cache first), or by public URL.
- **User recording**: Record audio from your device microphone via the web UI, then broadcast it. Requires HTTPS (browsers block microphone access without SSL). The server uses a self-signed certificate, so a browser security warning is expected.

## Configuration

| Key | Description |
|-----|-------------|
| `announce_volume` | Default volume (0-100) for announcements |
| `tts_default_lang` | Default language code for TTS (e.g. `en`) |
| `tts_assets_cache_path` | Directory for cached TTS audio files and saved assets |
| HTTPS cert/key settings | Passed to `HttpsServer` for microphone recording support (see `https_server.py`) |

## WWW

- `/` - Web UI for TTS input and microphone recording (served from `www/` directory, available over both HTTP and HTTPS)
- `/announce_tts?phrase=X&lang=X&vol=N` - Trigger a TTS announcement
- `/announce_user_recording` - Upload and announce a recorded audio file (PUT/POST, `audio_data` multipart field)
- `/ls_speakers` - JSON array of discovered Sonos speaker names (sorted)
- `/announcement_history` - JSON array of the 10 most recent announcements
- `/svc_config` - JSON with internal config (HTTPS server URL)
- `/tts/*` - Cached TTS audio assets (served to Sonos speakers over HTTP)

## HTTPS

An HTTPS server is started alongside the normal HTTP server. HTTP routes `/zmw.css` and `/zmw.js` are mirrored to HTTPS. The microphone recording UI requires HTTPS because browsers require a secure context for `getUserMedia`. Sonos speakers fetch audio over HTTP (they cannot validate self-signed certificates).
