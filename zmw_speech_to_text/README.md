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
