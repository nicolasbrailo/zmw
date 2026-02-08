include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/../zz2m")"

test_listen:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_cronenbergs/#'

test_get_stats:
	mosquitto_pub -t 'zmw_cronenbergs/get_stats' -m '{}'

test_get_mqtt_description:
	mosquitto_pub -t 'zmw_cronenbergs/get_mqtt_description' -m '{}'

