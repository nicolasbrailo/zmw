# ZmwTelegram

MQTT-to-Telegram bridge for bidirectional messaging. Runs a long-polling Telegram bot that relays commands and voice messages over MQTT, and allows other services to send text or photos through Telegram.

## Configuration

| Key | Description |
|-----|-------------|
| `tok` | Telegram bot API token |
| `bot_name` | Display name for the bot |
| `bcast_chat_id` | Default chat ID for outgoing messages |
| `accepted_chat_ids` | List of chat IDs the bot will respond to |
| `topic_map_chat` | Map of topic names to chat IDs for routing messages to specific chats |
| `short_poll_interval_secs` | Polling interval when active |
| `long_poll_interval_secs` | Polling interval when idle |
| `msg_history_len` | Number of messages to keep in history |
| `voice_download_path` | Directory for downloaded voice/audio files |

## WWW

- `/` - React monitoring UI (served from `www/` directory)
- `/messages` - JSON array of message history (sent and received)

## Rate Limiting

Outgoing messages are rate-limited to 3 messages per 60 seconds. If the limit is exceeded, further messages are dropped and the cooldown resets with each attempt (i.e. the window only expires after 60 seconds of silence).

## Voice Processing

Voice and audio messages are downloaded and transcoded to WAV (PCM 16-bit, 16kHz mono) for STT compatibility. Constraints:
- Messages longer than 60 seconds are dropped
- Transcoded WAV files larger than 5MB are discarded
- At most 30 voice files are kept on disk; oldest are cleaned up automatically
- Supported input formats: OGG, MP3, M4A, WAV, FLAC, AAC

## Built-in Telegram Commands

- `/ping` - Replies with PONG, or echoes back arguments
- `/stfu <minutes>` - Suppresses all outgoing messages for N minutes (default 10)
