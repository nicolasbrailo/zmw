# ZmwWhatsapp

MQTT-to-WhatsApp bridge for sending photos and messages via the WhatsApp Business Cloud API. Uses Facebook's Graph API to upload media and send template-based messages to configured phone numbers.

## Configuration

| Key | Description |
|-----|-------------|
| `tok` | WhatsApp Business API permanent access token |
| `from_number` | Origin phone number ID (from the Facebook developer dashboard) |
| `notify_targets` | List of target phone numbers to send messages to |
| `msg_history_len` | Number of message events to keep in history |

## WWW

- `/` - Monitoring UI (served from `www/` directory)
- `/messages` - JSON array of message history events

## Rate Limiting

Outgoing messages are rate-limited to 3 messages per 60 seconds. If the limit is exceeded, further messages are dropped and the cooldown resets with each attempt (i.e. the window only expires after 60 seconds of silence).

## Notes

- Text messages (`send_text`) are not yet implemented; the command is accepted but logs a warning and records the attempt.
- Photos are sent via WhatsApp template messages (`sample_purchase_feedback` by default), because the API does not allow sending standalone images to users who haven't recently interacted with the bot.
- Considerable setup is required on the Facebook developer dashboard (developer account, business app, WhatsApp integration, phone number enrollment, permanent token). See `whatsapp.py` for detailed setup instructions.
