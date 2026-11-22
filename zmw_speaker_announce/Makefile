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
	mosquitto_pub -t 'zmw_speaker_announce/tts' -m '{"msg": "test.", "lang": "en", "speakers": ["Batioficina", "portaloficina"]}'

test_bot_announce:
	# Same as ZmwTelegram relaying '/bot_shout {"msg": "bot test", "speakers": ["Batioficina"]}': args are split on ' '
	mosquitto_pub -t 'zmw_telegram/on_command/bot_shout' -m '{"cmd": "/bot_shout", "cmd_args": ["{\"msg\":", "\"bot", "test\",", "\"speakers\":", "[\"portaloficina\", \"Batioficina\"]}"]}'

test_save_asset:
	mosquitto_pub -t 'zmw_speaker_announce/save_asset' -m '{"local_path": "/home/batman/run/baticasa/tmp/test.mp3"}'
test_announce_asset:
	mosquitto_pub -t 'zmw_speaker_announce/play_asset' -m '{"name": "test.mp3", "vol": "default"}'
test_announce_local_asset:
	mosquitto_pub -t 'zmw_speaker_announce/play_asset' -m '{"local_path": "/home/batman/run/baticasa/tmp/test.mp3"}'

test_sub_all:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_speaker_announce/#'

test_svc_ping:
	mosquitto_pub -t 'svc_ping_bcast' -m '{}'
test_svc_ping_listen:
	# Use this to get the http url of the service
	mosquitto_sub -v -h 127.0.0.1 -t 'svc_announce_bcast/#' | grep zmw_speaker_announce

