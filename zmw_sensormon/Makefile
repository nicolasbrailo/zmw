ZZMW_LIB_EXTRAS = [z2m]
include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base

test_listen:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_sensormon/#'

SENSOR ?= TempSensor_LivingRoom
test_get_sensor_values:
	mosquitto_pub -t 'zmw_sensormon/get_sensor_values' -m '{"name": "$(SENSOR)"}'

METRIC ?= temperature
test_get_all_sensor_values:
	mosquitto_pub -t 'zmw_sensormon/get_all_sensor_values' -m '{"metric": "$(METRIC)"}'

test_get_known_sensors:
	mosquitto_pub -t 'zmw_sensormon/get_known_sensors' -m '{}'

test_get_known_metrics:
	mosquitto_pub -t 'zmw_sensormon/get_known_metrics' -m '{}'

test_get_sensors_measuring:
	mosquitto_pub -t 'zmw_sensormon/get_sensors_measuring' -m '{"metric": "$(METRIC)"}'

test_get_mqtt_description:
	mosquitto_pub -t 'zmw_sensormon/get_mqtt_description' -m '{}'

