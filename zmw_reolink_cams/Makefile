include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/../zext_libs/reolink_aio")"
	pipenv install flask

test_listen:
	mosquitto_sub -h 127.0.0.1 -t 'zmw_reolink_cams/#'

test_mqtt_snap:
	mosquitto_pub -t 'zmw_reolink_cams/snap' -m '{"cam_host": "10.0.0.20"}'

test_mqtt_rec:
	mosquitto_pub -t 'zmw_reolink_cams/rec' -m '{"cam_host": "10.0.0.20", "secs": 5}'

test_ls_cams:
	mosquitto_pub -t 'zmw_reolink_cams/ls_cams' -m '{}'

test_get_mqtt_description:
	mosquitto_pub -t 'zmw_reolink_cams/get_mqtt_description' -m '{}'

