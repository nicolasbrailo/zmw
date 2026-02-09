include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install spotipy

sub_all:
	mosquitto_sub -v -h localhost -p 1883 -t 'zmw_spotify/#' -v
test_publish_state:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_spotify/get_status' -m '{}'
test_stop:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_spotify/stop' -m '{}'
test_toggle_play:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_spotify/toggle_play' -m '{}'
test_next_track:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_spotify/relative_jump_to_track' -m '{"value": 1}'
test_prev_track:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_spotify/relative_jump_to_track' -m '{"value": -1}'
test_set_volume:
	mosquitto_pub -h localhost -p 1883 -t 'zmw_spotify/set_volume' -m '{"value": 50}'

