include ../common.mk

listen:
	mosquitto_sub -v -t 'zmw_speech_to_text/transcription'

# faster-whisper 1.2.1 calls av.open(metadata_errors=...), which PyAV 19 dropped
rebuild_deps: pipenv_rebuild_deps_base
	pipenv install faster-whisper "av<19"

