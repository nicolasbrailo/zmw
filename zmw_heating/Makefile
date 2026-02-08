include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/../zz2m")"
	pipenv install systemd-python

test_listen:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_heating/#'

test_svc_state:
	mosquitto_pub -t 'zmw_heating/svc_state' -m '{}'

test_get_cfg_rules:
	mosquitto_pub -t 'zmw_heating/get_cfg_rules' -m '{}'

test_active_schedule:
	mosquitto_pub -t 'zmw_heating/active_schedule' -m '{}'

HOURS ?= 1
test_boost:
	mosquitto_pub -t 'zmw_heating/boost' -m '{"hours": $(HOURS)}'

test_off_now:
	mosquitto_pub -t 'zmw_heating/off_now' -m '{}'

test_slot_toggle:
	mosquitto_pub -t 'zmw_heating/slot_toggle' -m '{"slot_nm": "8:00"}'

test_get_mqtt_description:
	mosquitto_pub -t 'zmw_heating/get_mqtt_description' -m '{}'

