include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/../zz2m")"
	pipenv install flask-sock

test_listen_all:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_lights/#'

test_get_lights:
	mosquitto_pub -t 'zmw_lights/get_lights' -m '{}'

test_get_switches:
	mosquitto_pub -t 'zmw_lights/get_switches' -m '{}'

PREFIX ?= TVRoom
test_all_lights_on:
	mosquitto_pub -t 'zmw_lights/all_lights_on' -m '{"prefix": "$(PREFIX)"}'

test_all_lights_off:
	mosquitto_pub -t 'zmw_lights/all_lights_off' -m '{"prefix": "$(PREFIX)"}'

test_get_mqtt_description:
	mosquitto_pub -t 'zmw_lights/get_mqtt_description' -m '{}'

