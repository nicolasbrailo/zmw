# ZmwSpeechToText

Speech-to-text service using faster-whisper. Transcribes (and optionally translates to English) audio from Telegram voice messages, HTTP uploads, or MQTT requests. Will publish results back to MQTT.

## MQTT

**Topic:** `zmw_speech_to_text`

**Methods (subscribe):**
- `transcribe` - Transcribe a file (`{path}` or `{wav_path, path}`)

**Announces (publish):**
- `transcription` - Transcription result (`{source, file, text, confidence}`)

## WWW Endpoints

- `GET /history` - Last 20 transcriptions as JSON
- `POST /transcribe` - Upload raw audio bytes, returns `{source, file, text, confidence}`

## Dependencies

- `ZmwTelegram` - Listens to `on_voice` for incoming voice messages
