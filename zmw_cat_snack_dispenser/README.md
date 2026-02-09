# ZmwCatSnackDispenser

Manages an Aqara ZNCWWSQ01LM (aqara.feeder.acn001) cat food dispenser via Zigbee2MQTT. Handles feeding schedules, monitors dispense events, and sends Telegram notifications on success, failure, or missed feedings.

![](README_screenshot.png)

## How It Works

The service uploads a feeding schedule to the Zigbee-connected dispenser unit, then monitors that the unit actually dispenses food at the scheduled times. If the unit misses a scheduled feeding (within a configurable tolerance), the service triggers an emergency remote dispense and sends an alert.

Dispense events are tracked regardless of source: scheduled, manual (button press on the unit), remote (Zigbee command), or requested via WWW/Telegram. Each event is logged in a rolling history with request/acknowledgement timestamps and portion counts.

## Configuration

| Key | Description |
|-----|-------------|
| `z2m_cat_feeder` | Zigbee2MQTT friendly name of the cat feeder device |
| `schedule_tolerance_secs` | Seconds to wait after a scheduled feeding before declaring it missed and triggering emergency dispense |
| `feeding_schedule` | List of schedule entries, each with `days`, `hour`, `minute`, `serving_size` |
| `telegram_on_error` | Send a Telegram message when a dispense event fails |
| `telegram_on_success` | Send a Telegram message on every successful dispense |
| `telegram_day_summary` | Send a daily summary after the last scheduled feeding |
| `telegram_summary_delay_minutes` | Minutes after last scheduled feeding to send the daily summary (default 5) |

### Schedule entry format

```json
{"days": "everyday", "hour": 17, "minute": 7, "serving_size": 1}
```

Valid `days` values: `everyday`, `workdays`, `weekend`, `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`, `mon-wed-fri-sun`, `tue-thu-sat`.

## WWW Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | React monitoring UI |
| `/feed_now` | GET | Trigger an immediate dispense |
| `/feed_history` | GET | JSON array of recent dispense events |
| `/feed_schedule` | GET | JSON array of the current feeding schedule |
| `/save_schedule` | PUT | Upload a new feeding schedule (JSON body). Validates and writes to config.json; service restarts automatically |

## Telegram Integration

On startup, registers a `/dispensecatsnacks` bot command with ZmwTelegram. Sends notifications for:
- Successful dispense events (if `telegram_on_success` is enabled)
- Failed or missed dispense events (if `telegram_on_error` is enabled)
- Daily feeding summary (if `telegram_day_summary` is enabled)

## Config Enforcement

The service continuously ensures the physical unit is configured correctly:
- Mode is set to `schedule` (not manual)
- The unit's internal schedule matches the configured `feeding_schedule`

If a mismatch is detected, the service corrects it automatically. A 1-second backoff prevents message loops when the unit echoes back partial config states.

## MQTT

**Topic:** `zmw_cat_feeder`

### Commands

#### `feed_now`

Dispense food. Response on feed_now_reply

| Param | Description |
|-------|-------------|
| `source?` | What triggered request |
| `serving_size?` | Number of portions |

#### `get_history`

Serving history. Response on get_history_reply

_No parameters._

#### `get_schedule`

Current feeding schedule. Response on get_schedule_reply

_No parameters._

#### `get_mqtt_description`

Service description

_No parameters._

### Announcements

#### `feed_now_reply`

Result of feed_now

| Param | Description |
|-------|-------------|
| `status` | ok|error |
| `error` | (on failure) description |

#### `get_history_reply`

Dispensing list

Payload: `[{'dispense_event_id?': 'int', 'time_requested': 'ISO timestamp', 'source': 'schedule|telegram|WWW|...', 'portions_dispensed?': 'int', 'weight_dispensed?': 'int', 'unit_acknowledged': 'bool', 'error?': 'string'}]`

#### `get_schedule_reply`

Feeding schedule

Payload: `[{'days': 'everyday|workdays|weekend|mon|mon,tue|...', 'hour': '0-23', 'minute': '0-59', 'serving_size': 'int'}]`

#### `get_mqtt_description_reply`

Service description
