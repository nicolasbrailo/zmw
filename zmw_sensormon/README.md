# ZmwSensormon

Sensor data monitoring and history service. Monitors Zigbee sensors (via Z2M), Shelly plugs (via ZmwShelly), and outside weather (via Open-Meteo), storing historical readings in a SQLite database.

![](README_screenshot.png)

## Features

- Monitors MQTT sensors: temperature, humidity, power, battery, contact, occupancy, voltage, energy, PM2.5, VOC, and more.
- Stores time-series readings in SQLite with configurable retention (by days).
- Computes virtual metrics from real ones (e.g. feels-like temperature from temperature + humidity).
- Integrates with Shelly plugs via the `zmw_shelly_plug` MQTT topic.
- Fetches outside weather (temperature, humidity) from the Open-Meteo API on a 5-minute interval.
- Provides a React UI with sensor badges and historical charts.

## Configuration

| Key | Description |
|-----|-------------|
| `db_path` | Path to the SQLite database file for sensor history |
| `retention_days` | Number of days of history to retain |
| `outside_latitude` | Latitude for outside weather queries |
| `outside_longitude` | Longitude for outside weather queries |

Standard keys (`mqtt_ip`, `mqtt_port`, `http_host`, `http_port`) are also supported.

## WWW Endpoints

| Endpoint | Description |
|----------|-------------|
| `/` | React monitoring UI (sensor badges, charts) |
| `/sensors/ls` | List all known sensor names (JSON array) |
| `/sensors/metrics` | List all known metric names (JSON array) |
| `/sensors/metrics/<sensor_name>` | List metrics available for a specific sensor |
| `/sensors/measuring/<metric>` | List sensors that measure a specific metric |
| `/sensors/get/<name>` | Get current values for a sensor (JSON dict). Checks Shelly devices first, then Z2M |
| `/sensors/get_all/<metric>` | Get current value of a metric across all sensors (JSON dict of sensor name to value) |
| `/sensors/get_metric_in_sensor_csv/<sensor>/<metric>` | Historical readings of one metric in one sensor (CSV) |
| `/sensors/get_metric_in_sensor_csv/<sensor>/<metric>/history/<unit>/<time>` | Same, with time window |
| `/sensors/get_all_metrics_in_sensor_csv/<sensor>` | All historical readings for one sensor (CSV) |
| `/sensors/get_single_metric_in_all_sensors_csv/<metric>` | One metric across all sensors (CSV) |
| `/sensors/get_single_metric_in_all_sensors_csv/<metric>/<unit>/<time>` | Same, with time window |
| `/sensors/gc_dead_sensors` | Trigger garbage collection of old sensor data |
| `/z2m/*` | Z2M web service endpoints |

## Virtual Metrics

When a sensor reports both `temperature` and `humidity`, a `feels_like_temp` virtual metric is automatically computed and stored:

- Hot+humid (T >= 27C, RH >= 40%): heat index (Rothfusz regression)
- Cold+humid (T < 20C, RH > 45%): humid-cold adjustment
- Otherwise: actual temperature

## Data Retention

Old samples are automatically purged daily at 02:22 based on the configured `retention_days`.

## MQTT

**Topic:** `zmw_sensormon`

### Commands

#### `get_sensor_values`

Get current values for a named sensor (Zigbee, Shelly, or virtual). Response on get_sensor_values_reply

| Param | Description |
|-------|-------------|
| `name` | Sensor name (e.g. 'Living_Room', 'Weather') |

#### `get_all_sensor_values`

Get the current value of a specific metric across all sensors that measure it. Response on get_all_sensor_values_reply

| Param | Description |
|-------|-------------|
| `metric` | Metric name (e.g. 'temperature', 'humidity', 'power_a') |

#### `get_known_sensors`

List all known sensor names. Response on get_known_sensors_reply

_No parameters._

#### `get_known_metrics`

List all metrics being measured across all sensors. Response on get_known_metrics_reply

_No parameters._

#### `get_sensors_measuring`

List sensors that measure a specific metric. Response on get_sensors_measuring_reply

| Param | Description |
|-------|-------------|
| `metric` | Metric name to query |

#### `get_mqtt_description`

Returns this MQTT API description. Response on get_mqtt_description_reply

_No parameters._

### Announcements

#### `get_sensor_values_reply`

Response to get_sensor_values. Dict of metric name to current value

| Param | Description |
|-------|-------------|
| `<metric>` | <value> |

#### `get_all_sensor_values_reply`

Response to get_all_sensor_values. Dict of sensor name to metric value

| Param | Description |
|-------|-------------|
| `<sensor_name>` | <value> |

#### `get_known_sensors_reply`

Response to get_known_sensors. List of sensor name strings

Payload: `['<sensor_name>']`

#### `get_known_metrics_reply`

Response to get_known_metrics. List of metric name strings

Payload: `['<metric_name>']`

#### `get_sensors_measuring_reply`

Response to get_sensors_measuring. List of sensor name strings

Payload: `['<sensor_name>']`

#### `get_mqtt_description_reply`

Response to get_mqtt_description. The MQTT API description dict
