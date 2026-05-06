include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/../zext_libs/wwwslide/HomeboardRemoteControl")"
	pipenv install -e "$(shell readlink -f "$(PWD)/../zext_libs/pymethodecache")"
	pipenv install picosvg
	pipenv install fonttools

clean_icons:
	pipenv run python clean_icons.py

test_listen:
	mosquitto_sub -h 127.0.0.1 -t 'zmw_homeboard/#'

HB ?= homeboarad-dev-pi4

test_ls:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/list' -m '{}'

test_next:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/next' -m '{"homeboard_id": "$(HB)"}'

test_prev:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/prev' -m '{"homeboard_id": "$(HB)"}'

test_overlay:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/set_svg_overlay' -m '{"homeboard_id": "$(HB)", "svg_file_path": "$(CURDIR)/test.svg"}'

test_announce:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/announce' -m '{"homeboard_id": "$(HB)", "msg": "Hello from ZMW"}'

test_weather:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/update_weather' -m '{}'

