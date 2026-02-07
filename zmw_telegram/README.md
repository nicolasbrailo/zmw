# ZmwTelegram

MQTT to Telegram bot bridge for bidirectional messaging.

Runs a Telegram bot that receives commands or voice messages and relays them over MQTT. Other services can register custom commands and send messages/photos through Telegram.

## MQTT

**Topic:** `mqtt_telegram`

**Methods (subscribe):**
- `register_command` - Register a Telegram command (`{cmd, descr}`)
- `send_photo` - Send photo to broadcast chat (`{path, msg?}`)
- `send_text` - Send text message (`{msg}`)

**Announces (publish):**
- `on_command/<cmd>` - Relayed Telegram command
- `on_voice` - Voice/audio message received (`{path, wav_path, from_id, from_name, chat_id, duration, original_mime_type}`). `path` is the original downloaded file, `wav_path` is the PCM 16kHz mono WAV transcode (null if ffmpeg failed or output too large). Voice messages longer than 60s are dropped.

## WWW

Provides a history of sent or received Telegram messages.

