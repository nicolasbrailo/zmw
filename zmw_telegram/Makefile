include ../common.mk

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install -e "$(shell readlink -f "$(PWD)/../zext_libs/PyTelegramBot")"
	pipenv install requests

test_send_photo:
	mosquitto_pub -t 'zmw_telegram/send_photo' -m '{"path": "/home/batman/src/BatiCasa/web_assets/doorbell_snap.jpg", "msg": "HOLA"}'

test_send_text:
	mosquitto_pub -t 'zmw_telegram/send_text' -m '{"msg": "HOLA"}'

test_reg_cmds:
	mosquitto_pub -t 'zmw_telegram/register_command' -m '{"cmd": "mqtt_ping", "descr": "Test mqtt proxy"}'

test_listen_all:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_telegram/#'

test_listen_cmds:
	mosquitto_sub -h 127.0.0.1 -t 'zmw_telegram/on_command/mqtt_ping'

test_listen_voice:
	mosquitto_sub -v -h 127.0.0.1 -t 'zmw_telegram/on_voice'

OGG ?= /home/batman/run/baticasa/zmw_telegram/voice_msgs/voice_6797373417_1770463102.ogg
WAV ?= /home/batman/run/baticasa/zmw_telegram/voice_msgs/voice_6797373417_1770463102.wav
test_voice_received:
	mosquitto_pub -t 'zmw_telegram/on_voice' -m '{"path": "$(OGG)", "wav_path": "$(WAV)", "from_id": 6797373417, "from_name": "N Fb", "chat_id": 6797373417, "duration": 1, "original_mime_type": "audio/ogg"}'

