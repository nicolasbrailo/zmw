include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install paho-mqtt

test_listen:
	mosquitto_sub -h 127.0.0.1 -t 'zmw_homeboard/#'
