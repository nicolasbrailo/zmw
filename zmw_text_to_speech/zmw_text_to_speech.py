import json
import os
import pathlib
import threading

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from tts import Tts

log = build_logger("ZmwTextToSpeech")


def _preload_tts():
    cfg = {}
    if os.path.exists('config.json'):
        with open('config.json', 'r') as fp:
            cfg = json.load(fp)
    return Tts(cfg.get('tts', {}))


class ZmwTextToSpeech(ZmwMqttService):
    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_text_to_speech", scheduler=_sched)
        self._tts = _preloaded_tts
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

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
                        "text": "Original text",
                        "voice_id": "Voice used",
                        "mp3_path": "Path to generated mp3 file",
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
        language = msg.get('language')
        speaker = msg.get('speaker')
        threading.Thread(
            target=self._synthesize_and_publish,
            args=(text, language, speaker), daemon=True).start()

    def _synthesize_and_publish(self, text, language, speaker):
        mp3_path, voice_id = self._tts.synthesize(text, language=language, speaker=speaker)
        result = {
            'text': text,
            'voice_id': voice_id,
            'mp3_path': mp3_path,
        }
        self.publish_own_svc_message("tts_reply", result)


_preloaded_tts = _preload_tts()
service_runner(ZmwTextToSpeech)
