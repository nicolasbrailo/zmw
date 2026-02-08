# ZmwCronenbergs

Scheduled home automation service. Runs calendar-based cron jobs for lights, notifications, and device health monitoring.

## Features

- **Auto lights off**: At a configured day/time, checks if any lights were left on, turns them off, and logs the event. Useful for weekday mornings after everyone leaves the house.
- **Vacation mode**: Simulates occupancy by turning random lights on in the late afternoon, dimming them in the evening, and shutting everything off at night.
- **Speaker announcements**: Plays scheduled TTS announcements through speakers at configured times (e.g. daily reminders).
- **Battery alerts**: Weekly check (Sundays at 10:00) for devices with battery below 30%, sends a Telegram notification listing them.

## Configuration

| Key | Description |
|-----|-------------|
| `auto_lights_off.enable` | Enable the automatic lights-off check |
| `auto_lights_off.day_of_week` | Cron day-of-week string (e.g. `"mon-fri"`) |
| `auto_lights_off.time` | Time to check, as `"HH:MM"` |
| `vacations_mode.enable` | Enable vacation mode light simulation |
| `vacations_mode.late_afternoon` | Time to turn random lights on, as `"HH:MM"` |
| `vacations_mode.evening` | Time to dim lights, as `"HH:MM"` |
| `vacations_mode.night` | Time to turn all lights off, as `"HH:MM"` |
| `speaker_announce` | List of `{time, msg, lang, vol}` objects for scheduled TTS |

## WWW

- `/` - React monitoring UI (served from `www/` directory)
- `/stats` - JSON object with light check history, vacation mode status, speaker announce config, and battery device data
- `/mock_auto_lights_off` - Debug: inserts mock light-check entries into history
- `/test_low_battery_notifs` - Debug: triggers a battery check immediately
- `/test_vacations_mode_late_afternoon` - Debug: triggers the vacation late-afternoon phase
- `/test_vacations_mode_evening` - Debug: triggers the vacation evening phase
- `/test_vacations_mode_night` - Debug: triggers the vacation night phase

## Service Dependencies

- **ZmwTelegram** - Used to send battery alert notifications and vacation mode status messages
- **ZmwSpeakerAnnounce** - Used to play scheduled TTS announcements

![](README_screenshot.png)

## MQTT

**Topic:** `zmw_cronenbergs`

### Commands

#### `get_stats`

Request service stats (light check history, vacation mode status, battery info). Response published on get_stats_reply

_No parameters._

### Announcements

#### `get_stats_reply`

Response to get_stats with full service statistics

| Param | Description |
|-------|-------------|
| `light_check_history` | List of recent light check events |
| `vacations_mode` | Whether vacation mode is enabled |
| `speaker_announce` | Configured speaker announcements |
| `battery_things` | List of devices with battery levels |

#### `get_mqtt_description_reply`

Response to get_mqtt_description with this service's MQTT API

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |
