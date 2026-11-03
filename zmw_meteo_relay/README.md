# ZmwMeteoRelay

Caching relay for [Open-Meteo](https://open-meteo.com). Every weather client in the house (sensormon, homeboard, AstroDock, ...) asks this service instead of Open-Meteo, so the house makes one request per location every N minutes no matter how many clients there are.

- Clients ask for the default location (from `config.json`) or for a lat/lon.
- Requested locations become *known locations*. A request within `dedup_radius_km` of a known location is served from it; otherwise a new known location is created and fetched on the spot. Beyond `max_known_locations`, the least recently requested one is forgotten (never the default).
- Every known location is refreshed every `update_interval_minutes`. A failed fetch is retried after `retry_base_secs`, doubling each time; once the next retry would land after the next periodic update, retries stop and the periodic update takes over (starting a new backoff sequence if it fails too). Clients keep getting the last good report meanwhile.
- Every successful fetch is announced on `zmw_meteo_relay/weather_updated`, so clients that want each new report (eg sensormon, recording history) can subscribe instead of polling. They still need one explicit request at startup.
- Known locations and their last report persist across restarts (`run_state_cache.json`).
- The report is the Open-Meteo `/v1/forecast` response, verbatim. All clients share it, so the service asks for a superset of the fields they need (current, hourly and daily blocks, 3 days, `timezone=auto`); override with `open_meteo_params` in `config.json`.

## Configuration

| Key | Description |
|-----|-------------|
| `default_location` | Required. `{"lat": ..., "lon": ...}`, served when a request has no location |
| `update_interval_minutes` | Refresh interval for all known locations (default: `30`) |
| `dedup_radius_km` | Requests this close to a known location reuse it (default: `3.0`) |
| `max_known_locations` | Cap on known locations; LRU eviction (default: `20`) |
| `retry_base_secs` | First retry delay after a failure, doubled per failure (default: `30`) |
| `open_meteo_url` | Forecast endpoint (default: `https://api.open-meteo.com/v1/forecast`) |
| `open_meteo_params` | Query params sent to Open-Meteo, except lat/lon (default: see `_DEFAULT_OPEN_METEO_PARAMS`) |

## WWW

- `/` -- Monitoring UI: known locations with their last report, and the last 10 clients
- `GET /weather` -- Report for the default location
- `GET /weather/<lat>/<lon>` -- Report for a location, eg `/weather/51.54/-0.13`
- `GET /status` -- Known locations (with reports) and recent clients, as JSON

`/weather` responses are the Open-Meteo JSON verbatim, with `X-Meteo-Relay-Fetched-At` and `X-Meteo-Relay-Location` headers. Errors are `400` (bad coordinates) or `503` (no data yet, eg Open-Meteo is down and nothing is cached), with `{"error": ...}`. Add `?client=<name>` to name yourself in the UI; otherwise clients are listed by IP.

## MQTT

**Topic:** `zmw_meteo_relay`

### Commands

#### `get_weather`

Get the weather report for a location (default location if lat/lon are omitted). Response on get_weather_reply

| Param | Description |
|-------|-------------|
| `lat?` | Latitude |
| `lon?` | Longitude |
| `client?` | Name of the requester, shown in the UI and echoed in the reply |

#### `get_known_locations`

List known locations and their fetch status. Response on get_known_locations_reply

_No parameters._

### Announcements

#### `weather_updated`

A new report was fetched from Open-Meteo for a known location (periodic update, retry, or a new location). Subscribe to this instead of polling

| Param | Description |
|-------|-------------|
| `location` | Known location: {id, lat, lon, is_default} |
| `fetched_at` | When the report was fetched from Open-Meteo |
| `weather` | Open-Meteo forecast response, verbatim |

#### `get_weather_reply`

Weather report. `weather` is the Open-Meteo response verbatim, or null if no data is available (see `error`)

| Param | Description |
|-------|-------------|
| `lat` | Requested latitude (null for default) |
| `lon` | Requested longitude (null for default) |
| `client` | Echo of the requester's client name |
| `location` | Known location serving the request: {id, lat, lon, is_default} |
| `fetched_at` | When the report was fetched from Open-Meteo |
| `weather` | Open-Meteo forecast response |
| `error?` | Set if no data is available |

#### `get_known_locations_reply`

Known locations

Payload: `[{'id': 'Location id', 'lat': 'Latitude', 'lon': 'Longitude', 'is_default': 'True for the default location', 'fetched_at': 'Last good fetch', 'last_error': 'Last fetch error, null if healthy'}]`

#### `get_mqtt_description_reply`

Service description

| Param | Description |
|-------|-------------|
| `commands` | {} |
| `announcements` | {} |
