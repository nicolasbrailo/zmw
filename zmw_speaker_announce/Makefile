include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install flask
	pipenv install aiohttp
	pipenv install soco

test_ls:
	mosquitto_pub -t 'zmw_speaker_announce/ls' -m '{}'

test_announce_www:
	mosquitto_pub -t 'zmw_speaker_announce/play_asset' -m '{"public_www": "http://10.0.0.10:4211/beep.mp3", "vol": "default"}'

test_announce_tts:
	mosquitto_pub -t 'zmw_speaker_announce/tts' -m '{"msg": "test", "lang": "en", "vol":40, "speakers": ["Batioficina"]}'

test_save_asset:
	mosquitto_pub -t 'zmw_speaker_announce/save_asset' -m '{"local_path": "/tmp/test.mp3"}'
test_announce_asset:
	mosquitto_pub -t 'zmw_speaker_announce/play_asset' -m '{"name": "test.mp3", "vol": "default"}'
test_announce_local_asset:
	mosquitto_pub -t 'zmw_speaker_announce/play_asset' -m '{"local_path": "/tmp/test.mp3"}'

test_sub_all:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_speaker_announce/#'

test_svc_ping:
	mosquitto_pub -t 'svc_ping_bcast' -m '{}'
test_svc_ping_listen:
	# Use this to get the http url of the service
	mosquitto_sub -v -h 127.0.0.1 -t 'svc_announce_bcast/#' | grep zmw_speaker_announce

