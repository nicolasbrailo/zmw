include ../common.mk

listen:
	mosquitto_sub -v -t 'zmw_text_to_speech/#'

say:
	mosquitto_pub -t 'zmw_text_to_speech/tts' -m '{"text": "Hello world"}'

say_lang:
	mosquitto_pub -t 'zmw_text_to_speech/tts' -m '{"text": "Hola mundo", "language": "es"}'

say_speaker:
	mosquitto_pub -t 'zmw_text_to_speech/tts' -m '{"text": "Hello world", "speaker": "en_GB-alan-medium"}'

voices:
	mosquitto_pub -t 'zmw_text_to_speech/get_voices' -m '{}'

rebuild_deps: pipenv_rebuild_deps_base
	pipenv install piper-tts

PIPER_VOICES_BASE = https://huggingface.co/rhasspy/piper-voices/resolve/main

download_model:
	mkdir -p ./tts_model
	cd ./tts_model && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_US/lessac/medium/en_US-lessac-medium.onnx' && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json' && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_GB/cori/medium/en_GB-cori-medium.onnx' && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_GB/cori/medium/en_GB-cori-medium.onnx.json' && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_GB/alan/medium/en_GB-alan-medium.onnx' && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json' && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_US/kathleen/low/en_US-kathleen-low.onnx' && \
		wget -nc '$(PIPER_VOICES_BASE)/en/en_US/kathleen/low/en_US-kathleen-low.onnx.json' && \
		wget -nc '$(PIPER_VOICES_BASE)/es/es_AR/daniela/high/es_AR-daniela-high.onnx' && \
		wget -nc '$(PIPER_VOICES_BASE)/es/es_AR/daniela/high/es_AR-daniela-high.onnx.json' && \
		wget -nc '$(PIPER_VOICES_BASE)/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx' && \
		wget -nc '$(PIPER_VOICES_BASE)/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json' && \
		wget -nc '$(PIPER_VOICES_BASE)/bg/bg_BG/dimitar/medium/bg_BG-dimitar-medium.onnx' && \
		wget -nc '$(PIPER_VOICES_BASE)/bg/bg_BG/dimitar/medium/bg_BG-dimitar-medium.onnx.json'

