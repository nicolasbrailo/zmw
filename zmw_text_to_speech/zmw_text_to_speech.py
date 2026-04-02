import datetime
import json
import os
import pathlib
import threading
from collections import deque

from flask import request, send_file

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from fuzzy_tts import FuzzyTts
from tts import Tts

log = build_logger("ZmwTextToSpeech")


def _preload_models():
    cfg = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r') as fp:
            cfg = json.load(fp)
    tts_cfg = cfg.get('tts', {})
    return Tts(tts_cfg), FuzzyTts(
        tts_cfg.get('fuzzy_model_path'),
        temperature=tts_cfg.get('fuzzy_temperature', 0.9),
    )


class ZmwTextToSpeech(ZmwMqttService):
    _MAX_HISTORY = 20

    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_text_to_speech", scheduler=_sched)
        self._tts, self._fuzzy_tts = _preloaded_models
        self._history = deque(maxlen=self._MAX_HISTORY)
        self._history_lock = threading.Lock()

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/voices', lambda: json.dumps(self._tts.get_voices()))
        www.serve_url('/tts_history', lambda: json.dumps(list(self._history)))
        www.serve_url('/synthesize', self._on_http_synthesize, methods=['PUT'])
        www.serve_url('/tts_download', self._on_http_download)

    def get_mqtt_description(self):
        return {
            "description": "Text-to-speech service. Receives text via MQTT, generates mp3, publishes path back.",
            "meta": self.get_service_meta(),
            "commands": {
                "tts": {
                    "description": "Generate speech from text",
                    "params": {
                        "text": "Text to synthesize",
                        "language?": "Language or locale code (e.g. en, en_US, es). Defaults to config.",
                        "speaker?": "Voice ID (e.g. en_GB-cori-medium). Overrides language.",
                        "fuzzy?": "If true, paraphrase text using the voice's personality before synthesis. Requires a personality configured for the resolved voice.",
                    }
                },
                "get_voices": {
                    "description": "List available voices. Response on get_voices_reply",
                    "params": {}
                },
            },
            "announcements": {
                "tts_reply": {
                    "description": "A synthesis completed",
                    "payload": {
                        "text": "Text that was synthesized (may be paraphrased if fuzzy)",
                        "original_text": "Original input text before paraphrasing",
                        "voice_id": "Voice used",
                        "mp3_path": "Path to generated mp3 file",
                        "fuzzy": "Whether fuzzy paraphrasing was applied",
                    }
                },
                "get_voices_reply": {
                    "description": "Available voices",
                    "payload": [{"voice_id": "ID", "name": "Name", "locale": "Locale", "lang": "Lang", "quality": "Quality"}]
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return
        match subtopic:
            case "tts":
                self._on_mqtt_synthesize(payload)
            case "get_voices":
                self.publish_own_svc_message("get_voices_reply", self._tts.get_voices())
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

    def _on_mqtt_synthesize(self, msg):
        text = msg.get('text')
        if not text:
            log.error("Synthesize request has no text: %s", msg)
            return
        language = msg.get('language') or msg.get('lang')
        speaker = msg.get('speaker')
        fuzzy = bool(msg.get('fuzzy', False))
        threading.Thread(
            target=self._synthesize_and_publish,
            args=(text, language, speaker, fuzzy), daemon=True).start()

    def _on_http_synthesize(self):
        data = request.get_json(force=True)
        text = data.get('text', '').strip()
        if not text:
            return json.dumps({'error': 'No text provided'}), 400
        speaker = data.get('speaker')
        fuzzy = bool(data.get('fuzzy', False))
        threading.Thread(
            target=self._synthesize_and_publish,
            args=(text, None, speaker, fuzzy), daemon=True).start()
        return json.dumps({'status': 'ok'})

    def _on_http_download(self):
        mp3_path = request.args.get('path', '')
        if not mp3_path or not os.path.isfile(mp3_path):
            return json.dumps({'error': 'File not found'}), 404
        return send_file(mp3_path, mimetype='audio/mpeg')

    def _add_history(self, result):
        entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'text': result['text'],
            'original_text': result['original_text'],
            'voice_id': result['voice_id'],
            'fuzzy': result['fuzzy'],
            'mp3_url': f'/tts_download?path={result["mp3_path"]}',
        }
        with self._history_lock:
            self._history.append(entry)

    def _synthesize_and_publish(self, text, language, speaker, fuzzy):
        log.info("Received request to TTS '%s'", text)

        fuzzy_applied = False
        synth_text = text
        fuzzy_cfg = self._tts.get_personality(language, speaker)
        if fuzzy and fuzzy_cfg:
            system_prompt, examples = fuzzy_cfg
            log.info("Requested fuzzy TTS, paraphrasing...")
            paraphrased = self._fuzzy_tts.paraphrase(text, system_prompt, examples)
            if paraphrased:
                synth_text = paraphrased
                log.info("Paraphrased '%s' -> '%s'", text, paraphrased)
                fuzzy_applied = True
            else:
                log.warning("Fuzzy paraphrase failed, falling back to original text")

        mp3_path, voice_id = self._tts.synthesize(synth_text, language=language, speaker=speaker)
        result = {
            'text': synth_text,
            'original_text': text,
            'voice_id': voice_id,
            'mp3_path': mp3_path,
            'fuzzy': fuzzy_applied,
        }
        self._add_history(result)
        self.publish_own_svc_message("tts_reply", result)
        log.info("TTS done result='%s'", result)


_preloaded_models = _preload_models()  # (Tts, FuzzyTts) tuple
service_runner(ZmwTextToSpeech)
