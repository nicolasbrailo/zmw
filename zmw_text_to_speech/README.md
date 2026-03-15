# ZmwTextToSpeech

Offline text-to-speech service using [Piper TTS](https://github.com/rhasspy/piper). Receives text via MQTT, generates an mp3 file, and publishes the asset path back. Supports multiple voices and languages with automatic voice resolution.

Piper was chosen over Kokoro-82M because it runs well on low-power CPU hardware (2017 NUC / Raspberry Pi class). Kokoro produces more natural speech but is too slow on CPU-only devices (~3.5x slower than real-time vs Piper's ~0.2x).

Requires `ffmpeg` installed on the system for WAV-to-mp3 conversion. Install python deps with `make rebuild_deps` and download models with `make download_model`.

## Voice resolution

Piper models are language-specific (one model per voice/language). When a TTS request arrives, the voice is resolved in this order:

1. If `speaker` is specified, use that exact voice ID
2. If `language` is a full locale (e.g. `en_US`), match voices for that locale
3. If `language` is a language code (e.g. `en`), match using the defaults map, then first available voice
4. If no language, use `default_language` from config
5. Last resort: first voice alphabetically

The `defaults` config allows pinning a preferred voice per language (e.g. always use `es_AR-daniela-high` for any `es` request).

## Output

Generated mp3 files are stored in the system temp directory by default. Filenames are content-addressable: an md5 hash of the text and voice ID, so identical requests reuse the same file (e.g. `tts_7ab381c9a196.mp3`).

## Adding new voices

1. Find a voice at [Piper voice samples](https://rhasspy.github.io/piper-samples/)
2. Download the `.onnx` and `.onnx.json` files into `model_dir` (add a wget line to `make download_model`)
3. The voice is auto-discovered on next startup — no code changes needed
4. Optionally add a `defaults` entry to pin it as the preferred voice for a language

Models are available at `https://huggingface.co/rhasspy/piper-voices/tree/main`, organized as `{lang}/{locale}/{name}/{quality}/{locale}-{name}-{quality}.onnx`.


## File structure

| File | Purpose |
|------|---------|
| `zmw_text_to_speech.py` | Main MQTT service entry point. Handles commands, delegates to `Tts`. |
| `tts.py` | Piper TTS wrapper. Multi-model auto-discovery, voice resolution, WAV-to-mp3 conversion. Runnable standalone. |
| `config.template.json` | Configuration template. |
| `Makefile` | Build, test, and model download targets. |


## Configuration

| Key | Description |
|-----|-------------|
| `model_dir` | Directory containing `.onnx` voice models. All models are auto-discovered at startup. |
| `default_language` | Fallback language when no language is specified in a request (e.g. `en`) |
| `defaults` | Map of language/locale to voice ID overrides (e.g. `{"es": "es_AR-daniela-high"}`) |

## MQTT

**Topic:** `zmw_text_to_speech`

### Commands

#### `tts`

Generate speech from text

| Param | Description |
|-------|-------------|
| `text` | Text to synthesize |
| `language?` | Language or locale code (e.g. en, en_US, es). Defaults to config. |
| `speaker?` | Voice ID (e.g. en_GB-cori-medium). Overrides language. |

#### `get_voices`

List available voices. Response on get_voices_reply

_No parameters._

### Announcements

#### `tts_reply`

A synthesis completed

| Param | Description |
|-------|-------------|
| `text` | Original text |
| `voice_id` | Voice used |
| `mp3_path` | Path to generated mp3 file |

#### `get_voices_reply`

Available voices

Payload: `[{'voice_id': 'ID', 'name': 'Name', 'locale': 'Locale', 'lang': 'Lang', 'quality': 'Quality'}]`

#### `get_mqtt_description_reply`

Service description

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |
