include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/../zext_libs/wwwslide/HomeboardRemoteControl")"

test_listen:
	mosquitto_sub -h 127.0.0.1 -t 'zmw_homeboard/#'

HB ?= homeboard

test_next:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/next' -m '{"homeboard_id": "$(HB)"}'

test_prev:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/prev' -m '{"homeboard_id": "$(HB)"}'
