ZZMW_LIB_EXTRAS = [z2m]
include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base

# Test targets - simulate contact sensor events
door_open:
	mosquitto_pub -h localhost -p 1883 -t 'zigbee2mqtt/ContactSensor_FrontDoor' -m '{"contact": false}'
door_close:
	mosquitto_pub -h localhost -p 1883 -t 'zigbee2mqtt/ContactSensor_FrontDoor' -m '{"contact": true}'
window_open:
	mosquitto_pub -h localhost -p 1883 -t 'zigbee2mqtt/ContactSensor_BathroomWindow' -m '{"contact": false}'
window_close:
	mosquitto_pub -h localhost -p 1883 -t 'zigbee2mqtt/ContactSensor_BathroomWindow' -m '{"contact": true}'
listen_mqtt:
	mosquitto_sub -h localhost -p 1883 -t 'zmw_contactmon/#' -v
pub_state:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_contactmon/publish_state' -m '{}'
skip_chimes:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_contactmon/skip_chimes' -m '{"timeout": 42}'
enable_chimes:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_contactmon/enable_chimes' -m '{}'
