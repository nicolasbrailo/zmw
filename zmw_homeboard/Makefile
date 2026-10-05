include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install qrcode
	pipenv install picosvg
	pipenv install fonttools

clean_icons:
	pipenv run python clean_icons.py

test_listen:
	mosquitto_sub -h 127.0.0.1 -t 'zmw_homeboard/#'

HB ?= homeboard

test_ls:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/list' -m '{}'

test_next:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/next' -m '{"homeboard_id": "$(HB)"}'

test_prev:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/prev' -m '{"homeboard_id": "$(HB)"}'

test_doorbell_ring:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/doorbell_ring' -m '{"homeboard_id": "$(HB)", "rtsp_urls": {"sub": "rtsp://admin:@10.10.30.11:554/h264Preview_01_sub"}}'

test_overlay:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/set_svg_overlay' -m '{"homeboard_id": "$(HB)", "svg_file_path": "$(CURDIR)/test.svg"}'

test_announce:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/announce' -m '{"homeboard_id": "$(HB)", "msg": "Hello! ZMW announce test", "timeout": 15}'

test_weather:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/update_weather' -m '{}'

test_album_filter:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/set_album_filter' -m '{"name": "portalgo-*", "from_year": 2019}'

test_album_filter_clear:
	mosquitto_pub -h 127.0.0.1 -t 'zmw_homeboard/set_album_filter' -m '{}'
