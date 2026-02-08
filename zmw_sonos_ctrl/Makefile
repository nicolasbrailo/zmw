include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install soco flask-sock

sub_all:
	mosquitto_sub -v -h localhost -p 1883 -t 'zmw_sstest/#' -v

test_switch_source:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_sstest/switch_source' -m '{"source": "spotify"}'

test_switch_linein:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_sstest/switch_source' -m '{"source": "line-in"}'

test_listen:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_sonos_ctrl/#'

test_world_state:
	mosquitto_pub -t 'zmw_sonos_ctrl/world_state' -m '{}'

test_ls_speakers:
	mosquitto_pub -t 'zmw_sonos_ctrl/ls_speakers' -m '{}'

test_get_sonos_play_uris:
	mosquitto_pub -t 'zmw_sonos_ctrl/get_sonos_play_uris' -m '{}'

test_get_spotify_context:
	mosquitto_pub -t 'zmw_sonos_ctrl/get_spotify_context' -m '{}'

test_stop_all:
	mosquitto_pub -t 'zmw_sonos_ctrl/stop_all' -m '{}'

test_volume_up:
	mosquitto_pub -t 'zmw_sonos_ctrl/volume_up' -m '{}'

test_volume_down:
	mosquitto_pub -t 'zmw_sonos_ctrl/volume_down' -m '{}'

test_next_track:
	mosquitto_pub -t 'zmw_sonos_ctrl/next_track' -m '{}'

test_prev_track:
	mosquitto_pub -t 'zmw_sonos_ctrl/prev_track' -m '{}'

test_spotify_hijack:
	mosquitto_pub -t 'zmw_sonos_ctrl/spotify_hijack' -m '{}'

test_spotify_hijack_or_toggle_play:
	mosquitto_pub -t 'zmw_sonos_ctrl/spotify_hijack_or_toggle_play' -m '{}'

test_get_mqtt_description:
	mosquitto_pub -t 'zmw_sonos_ctrl/get_mqtt_description' -m '{}'

