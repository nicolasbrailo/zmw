# ZmwSpeechToText

Offline speech-to-text service using faster-whisper. Transcribes audio from Telegram voice messages, HTTP uploads, or MQTT file-path requests, and publishes results back to MQTT. Optionally translates non-English audio to English in a single pass using Whisper's built-in translate task.

## Configuration

| Key | Description |
|-----|-------------|
| `stt.model_size` | Whisper model size (default: `tiny.en`). Options: `tiny`, `tiny.en`, `base`, `base.en`, `small`, `small.en`, `medium`, `medium.en`, `large-v2`, `large-v3` |
| `stt.compute_type` | Model precision (default: `int8`). Options: `int8`, `float16`, `float32` |
| `stt.local_files_only` | If `true`, only use already-downloaded models. Set to `false` on first run to download, then switch back to `true` |
| `stt.language` | Source language hint for Whisper (default: `en`). Set to `null` for auto-detection |
| `stt.task` | Whisper task (default: `translate`). Use `transcribe` to keep original language, `translate` to output English |
| `stt.beam_size` | Beam search width (default: `5`). Higher values are slower but may be more accurate |

## Dependencies

- `ZmwTelegram` -- Listens to `on_voice` announcements for incoming voice/audio messages. Received audio is transcribed and the result is published as a `transcription` announcement.

## WWW

- `/` -- Monitoring UI (served from `www/` directory)
- `POST /transcribe` -- Upload raw audio bytes, returns JSON `{source, file, text, confidence}`
- `GET /history` -- Last 20 transcription results as a JSON array

## Model Loading

The STT model is loaded in a background thread at startup. If loading fails (e.g., `local_files_only` is `true` but the model has not been downloaded), the service stays running but all transcription requests are rejected with a warning. To download the model for the first time, set `local_files_only` to `false`, restart the service, then optionally set it back to `true`.

## MQTT

**Topic:** `zmw_speech_to_text`

### Commands

#### `transcribe`

Transcribe an audio file at the given path

| Param | Description |
|-------|-------------|
| `wav_path` | (preferred) Path to a WAV file |
| `path` | (fallback) Path to any audio file |

#### `get_history`

Request transcription history. Response published on get_history_reply

_No parameters._

### Announcements

#### `transcription`

Published when a transcription completes (from any source: HTTP, MQTT, or Telegram voice)

| Param | Description |
|-------|-------------|
| `source` | Origin: 'http', 'mqtt', or 'telegram' |
| `file` | Path to audio file (null for HTTP uploads) |
| `text` | Transcribed text |
| `confidence` | {'language': 'Detected language code', 'language_prob': 'Language detection probability', 'avg_log_prob': 'Average log probability of segments', 'no_speech_prob': 'Probability of no speech in segments'} |

#### `get_history_reply`

Response to get_history. Array of recent transcription results (max 20)

Payload: `[{'source': 'Origin', 'file': 'Audio path', 'text': 'Transcribed text', 'confidence': 'Confidence metrics'}]`

#### `get_mqtt_description_reply`

Response to get_mqtt_description. Describes all MQTT commands and announcements for this service

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |
