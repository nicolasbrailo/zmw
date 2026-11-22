# ZmwSpeakerAnnounce

Speaker announcement service with TTS, pre-recorded asset playback, and live microphone recording support. Announcements play on all Sonos speakers on the network and on the homeboards that can play audio, or only on the ones requested.

## Speakers

A speaker is either a Sonos (by its name) or a homeboard (by its id, case-insensitive), and both can be mixed in one request. No list means all of them.

- **Sonos**: discovered on the network (or `speaker_ip_list`), played through the Sonos API.
- **Homeboards**: the ones ZmwHomeboard declares can play audio (`ls_audio_targets`, and `audio_targets` when that changes). Played by sending `announce_audio` to ZmwHomeboard for each one. While ZmwHomeboard is down, there are no homeboard speakers.

`announcement_in_progress` carries the requested `speakers`, so services mirroring the text (eg ZmwHomeboard) can show it only where the announcement plays.

![](README_screenshot.png)

## Modes

- **TTS**: Send a text phrase to be converted to speech and played on all speakers. Multiple languages are supported via the configured TTS engine. Supports "fuzzy" mode (default) which paraphrases text through a voice personality before synthesis — use the "Fast announce" button in the web UI to skip paraphrasing.
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
- `/announce_tts?phrase=X&lang=X&vol=N&fuzzy=true` - Trigger a TTS announcement (fuzzy defaults to true)
- `/announce_user_recording` - Upload and announce a recorded audio file (PUT/POST, `audio_data` multipart field)
- `/ls_speakers` - JSON array of speaker names: Sonos speakers, then homeboards (each sorted)
- `/announcement_history` - JSON array of the 10 most recent announcements
- `/svc_config` - JSON with internal config (HTTPS server URL)
- `/tts/*` - Cached TTS audio assets (served to Sonos speakers over HTTP)

## HTTPS

An HTTPS server is started alongside the normal HTTP server. HTTP routes `/zmw.css` and `/zmw.js` are mirrored to HTTPS. The microphone recording UI requires HTTPS because browsers require a secure context for `getUserMedia`. Sonos speakers fetch audio over HTTP (they cannot validate self-signed certificates).

## Telegram

Registers these commands with ZmwTelegram. The `bot_*` ones are meant for bots (eg an LLM sending a daily report), and are named `/bot_[service]_[command]` (Telegram only allows lowercase letters, digits and underscores in command names).

- `/shout <text>` - Announce text on all speakers, with the default voice and fuzzy mode.
- `/bot_shout {"msg": "text", "voice?": "name", "speakers?": ["name", ...]}` - Announce text, args as JSON. Never fuzzy (the text is already LLM-written), always uses ZmwTextToSpeech (never falls back to Google TTS, regardless of `tts_mode`) with a longer timeout, since reports can be long. TTS failures are reported back over Telegram.
  - `voice`: a voice name or voice_id, fuzzy matched: case and punctuation are ignored, and it matches part of the name (`glados`, `vincent`, or a description like `pirate`) or a misspelling (`galdos`). If missing, ambiguous, or not a known voice (only logged, not reported back), ZmwTextToSpeech picks its default voice for its own `default_language` (this service's `tts_default_lang` isn't used).
  - `speakers`: Sonos names and homeboard ids (see Speakers). If missing or empty, all speakers. Unknown names are skipped and only logged; if none match, nothing plays.
  - Volume can't be set, and `announce_volume` isn't applied: Sonos picks the volume (same as `/shout`).
- `/bot_shout_voices` - Replies with a JSON list of voices: `[{"voice": "Glados", "locale": "en_US"}, ...]`.
- `/bot_shout_speakers` - Replies with a JSON list of speakers: `[{"name": "SpeakerCocina", "kind": "sonos"}, {"name": "portalcocina", "kind": "homeboard"}, ...]`.

Replies go to ZmwTelegram's broadcast chat, which rate-limits outgoing messages. ZmwTelegram drops incoming messages over 2048 chars (including the command and its JSON), so keep reports under ~300 words.

## MQTT

**Topic:** `zmw_speaker_announce`

### Commands

#### `ls`

List speakers (Sonos and homeboards that can play audio). Response on ls_reply

_No parameters._

#### `tts`

Say a message out loud on speakers (text-to-speech). Use for announcements and notifications.

| Param | Description |
|-------|-------------|
| `msg` | Text to announce |
| `lang?` | Language code |
| `vol?` | Volume 0-100 |
| `fuzzy?` | Paraphrase text using voice personality before synthesis (default: true) |
| `speakers?` | List of speaker names, Sonos or homeboard (see ls). Default: all speakers |

#### `announcement_history`

Get service history. Response on announcement_history_reply

_No parameters._

#### `get_mqtt_description`

Service definition

_No parameters._

### Announcements

#### `ls_reply`

List of speaker names: Sonos speakers, then homeboard ids

Payload: `['speaker_name_1', 'speaker_name_2']`

#### `tts_reply`

Published when a TTS announcement completes. Contains generated asset paths

| Param | Description |
|-------|-------------|
| `local_path` | Filename generated TTS audio |
| `uri` | Public URL where TTS audio is served |

#### `announcement_in_progress`

Published when a spoken (TTS) announcement starts playing on the speakers. Lets other services mirror the announced text, on the same speakers

| Param | Description |
|-------|-------------|
| `msg` | The text being announced |
| `speakers` | Requested speaker names, Sonos or homeboard (null: all speakers) |

#### `currently_playing`

Published whenever the speakers are asked to play a sound (TTS, user recording or asset)

| Param | Description |
|-------|-------------|
| `uri` | URL of the audio being played |
| `volume` | Requested volume 0-100 (null: speaker default) |
| `speakers` | List of target speaker names, Sonos or homeboard (null: all speakers) |
| `msg?` | Original text of the TTS request; absent for recordings and assets |

#### `announcement_history_reply`

Announcement history

Payload: `[{'timestamp': 'ISO timestamp', 'source': 'Who requested it: mqtt, http, telegram_user or telegram_bot', 'phrase?': 'Text', 'lang': 'Requested language or voice', 'voice': 'Voice used (ZMW TTS voice_id, or google_tts:<lang>); null if not TTS', 'volume': 'Volume', 'uri': 'Asset URI'}]`

#### `get_mqtt_description_reply`

Service description

(this object)
