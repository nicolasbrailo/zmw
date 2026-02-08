import collections
import json
import os
import pathlib
import threading

from flask import request

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from stt import Stt

# TODO: Translation options
# Currently using Whisper's built-in translate task (audio -> English text in one pass).
# If translation quality isn't good enough, we can do two passes instead:
#   1. Whisper transcribe (task="transcribe", language=None) -> original language text
#   2. Translate text with MarianMT (Helsinki-NLP/opus-mt-{src}-en, ~300MB per language pair)
# MarianMT runs offline, via HuggingFace transformers, and gives better translations than
# Whisper's built-in translate for most language pairs.

log = build_logger("ZmwSpeechToText")


class ZmwSpeechToText(ZmwMqttService):
    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_speech_to_text", scheduler=_sched, svc_deps=['ZmwTelegram'])
        self._history = collections.deque(maxlen=20)
        self._stt = None
        self._stt_cfg = cfg.get('stt', {})
        threading.Thread(target=self._load_stt, daemon=True).start()
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/transcribe', self._http_transcribe, methods=['POST'])
        www.serve_url('/history', self._http_history)

    def _load_stt(self):
        try:
            self._stt = Stt(self._stt_cfg)
        except Exception:
            log.error("Failed to load STT model. If local_files_only is true, the model "
                      "must be downloaded first (set local_files_only to false, restart, "
                      "then set it back to true). Service will stay running but STT is disabled.")

    def get_mqtt_description(self):
        return {
            "commands": {
                "transcribe": {
                    "description": "Transcribe an audio file at the given path",
                    "params": {"wav_path": "(preferred) Path to a WAV file", "path": "(fallback) Path to any audio file"}
                },
                "get_history": {
                    "description": "Request transcription history. Response published on get_history_reply",
                    "params": {}
                },
            },
            "announcements": {
                "transcription": {
                    "description": "Published when a transcription completes (from any source: HTTP, MQTT, or Telegram voice)",
                    "payload": {"source": "Origin: 'http', 'mqtt', or 'telegram'", "file": "Path to audio file (null for HTTP uploads)", "text": "Transcribed text", "confidence": {"language": "Detected language code", "language_prob": "Language detection probability", "avg_log_prob": "Average log probability of segments", "no_speech_prob": "Probability of no speech in segments"}}
                },
                "get_history_reply": {
                    "description": "Response to get_history. Array of recent transcription results (max 20)",
                    "payload": [{"source": "Origin", "file": "Audio path", "text": "Transcribed text", "confidence": "Confidence metrics"}]
                },
                "get_mqtt_description_reply": {
                    "description": "Response to get_mqtt_description. Describes all MQTT commands and announcements for this service",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
        }

    def _http_transcribe(self):
        if not self._stt:
            return json.dumps({'error': 'STT model not loaded'}), 503
        audio_bytes = request.get_data()
        if not audio_bytes:
            return json.dumps({'error': 'No audio data received'}), 400
        text, confidence = self._stt.transcribe_bytes(audio_bytes)
        result = {'source': 'http', 'file': None, 'text': text, 'confidence': confidence}
        self._history.append(result)
        self.publish_own_svc_message("transcription", result)
        return json.dumps(result)

    def _http_history(self):
        return json.dumps(list(self._history))

    def on_dep_published_message(self, svc_name, subtopic, msg):
        match svc_name:
            case 'ZmwTelegram':
                if subtopic == "on_voice":
                    self._on_voice(msg)
            case _:
                log.debug("Ignoring message from %s/%s", svc_name, subtopic)

    def _on_voice(self, msg):
        if not self._stt:
            log.warning("Ignoring voice message, STT model not loaded")
            return
        path = msg.get('wav_path', msg.get('path'))
        if not path:
            log.error("Voice message has no path: %s", msg)
            return

        transcription = self._stt.transcribe_file(path)
        if not transcription:
            return
        text, confidence = transcription
        result = {'source': 'telegram', 'file': path, 'text': text, 'confidence': confidence}
        self._history.append(result)
        self.publish_own_svc_message("transcription", result)

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return
        match subtopic:
            case "transcribe":
                self._on_mqtt_transcribe(payload)
            case "get_history":
                self.publish_own_svc_message("get_history_reply",
                    list(self._history))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case "transcription":
                # Ignore self-echo of announcements
                pass
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

    def _on_mqtt_transcribe(self, msg):
        if not self._stt:
            log.warning("Ignoring MQTT transcribe request, STT model not loaded")
            return
        # Get wav path, fallback to whatever Telegram sent us (ogg?)
        path = msg.get('wav_path', msg.get('path'))
        if not path:
            log.error("MQTT transcribe request has no path: %s", msg)
            return
        transcription = self._stt.transcribe_file(path)
        if not transcription:
            return
        text, confidence = transcription
        result = {'source': 'mqtt', 'file': path, 'text': text, 'confidence': confidence}
        self._history.append(result)
        self.publish_own_svc_message("transcription", result)


service_runner(ZmwSpeechToText)
