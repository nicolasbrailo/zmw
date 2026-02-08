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

## MQTT

**Topic:** `zmw_telegram`

### Commands

#### `register_command`

Register a Telegram bot command that will be relayed over MQTT when invoked

| Param | Description |
|-------|-------------|
| `cmd` | Command name (without /) |
| `descr` | Help text for the command |

#### `send_photo`

Send a photo to a Telegram chat

| Param | Description |
|-------|-------------|
| `path` | Local file path to the image |
| `msg` | (optional) Caption |
| `topic` | (optional) Route to a specific chat via topic_map_chat |

#### `send_text`

Send a text message to a Telegram chat

| Param | Description |
|-------|-------------|
| `msg` | Message text |
| `topic` | (optional) Route to a specific chat via topic_map_chat |

#### `get_history`

Request message history. Response published on get_history_reply

_No parameters._

### Announcements

#### `on_command/<cmd>`

Published when a registered Telegram command is received

| Param | Description |
|-------|-------------|
| `cmd` | The command name |
| `cmd_args` | List of arguments |
| `from` | Sender info |
| `chat` | Chat info |

#### `on_voice`

Published when a voice/audio message is received (max 60s)

| Param | Description |
|-------|-------------|
| `path` | Original audio file path |
| `wav_path` | Transcoded WAV path (null if failed) |
| `from_id` | Sender ID |
| `from_name` | Sender name |
| `chat_id` | Chat ID |
| `duration` | Duration in seconds |
| `original_mime_type` | MIME type of original audio |

#### `get_history_reply`

Response to get_history. List of message objects

Payload: `[{'timestamp': 'ISO timestamp', 'direction': 'sent|received', 'message': 'Message content'}]`
