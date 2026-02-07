include ../common.mk

listen:
	mosquitto_sub -v -t 'zmw_speech_to_text/transcription'

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install faster-whisper

