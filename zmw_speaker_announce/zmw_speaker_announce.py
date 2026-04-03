"""MQTT speaker announcement service using Sonos."""
import json
import shutil
import os
import pathlib
import subprocess
import threading
from collections import deque
from datetime import datetime

from flask import abort, request

from zzmw_lib.logs import build_logger
from zzmw_lib.mqtt_request_reply import MqttRequestReply
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from https_server import HttpsServer
from sonos_helpers import get_sonos_by_name, config_soco_logger
from sonos_announce import sonos_announce
from tts import get_local_path_tts

log = build_logger("ZmwSpeakerAnnounce")
config_soco_logger(False)


def save_audio_as_mp3(audio_file, output_dir):
    """Save audio file as ogg, convert to mp3, return mp3 path. Returns None on error."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_filename = f"user_recording_{timestamp}"
    ogg_path = os.path.join(output_dir, f"{base_filename}.ogg")
    mp3_path = os.path.join(output_dir, f"{base_filename}.mp3")

    try:
        audio_file.save(ogg_path)
        subprocess.run(['ffmpeg', '-i', ogg_path, '-y', mp3_path], check=True, timeout=5)
    except subprocess.TimeoutExpired:
        log.error("ffmpeg conversion timed out for '%s'", ogg_path)
        return None
    except subprocess.CalledProcessError:
        log.error("ffmpeg conversion failed for '%s'", ogg_path, exc_info=True)
        return None
    except OSError as e:
        log.error("Failed to save/convert audio: %s", e)
        return None

    return mp3_path


GOOGLE_TTS_LANGUAGES = [
    {"value": "es-ES", "label": "ES"},
    {"value": "es-419", "label": "es 419"},
    {"value": "en-GB", "label": "EN GB"},
]

_ZMW_TTS_TIMEOUT = 10
_ZMW_TTS_VOICES_TIMEOUT = 2


class ZmwSpeakerAnnounce(ZmwMqttService):
    """MQTT proxy for Sonos speaker announcements."""
    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_speaker_announce", scheduler=_sched,
                         svc_deps=["ZmwTextToSpeech", "ZmwTelegram"])
        self._cfg = cfg
        self._announce_vol = cfg['announce_volume']
        self._announcement_history = deque(maxlen=10)

        # TTS mode: "auto" (default), "force_google_tts", "force_zmw_tts"
        self._tts_mode = cfg.get('tts_mode', 'auto')
        self._zmw_tts_voices = None

        self._rr = MqttRequestReply(self.message_svc)

        # Save cache path for tts and register it as a www dir, to serve assets
        self._tts_assets_cache_path = cfg['tts_assets_cache_path']
        if not os.path.isdir(self._tts_assets_cache_path):
            raise FileNotFoundError(f"Invalid cache path '{self._tts_assets_cache_path}'")

        # Create HTTPS server that proxies to the HTTP server
        # All endpoints registered on https_www will be available on both HTTP and HTTPS
        # Register TTS assets - Sonos uses HTTP (can't validate self-signed certs) so make sure HTTP works
        # User recording (mic) requires HTTPS, so make sure we can serve an HTTPS page
        self._https = HttpsServer(www, cfg)
        self._https.mirror_http_routes(['/zmw.css', '/zmw.js'])

        self._https.register_www_dir(cfg['tts_assets_cache_path'], '/tts/')
        self._public_tts_base = f"{www.public_url_base}/tts"
        log.info("Sonos will fetch TTS assets from HTTP server: %s", self._public_tts_base)

        # Register all other endpoints on both HTTP and HTTPS
        self._https.register_www_dir(os.path.join(pathlib.Path(__file__).parent.resolve(), 'www'), '/')
        self._https.serve_url('/announce_user_recording', self._announce_user_recording, methods=['PUT', 'POST'])
        self._https.serve_url('/announce_tts', self._www_announce_tts)
        self._https.serve_url('/ls_speakers', lambda: json.dumps(sorted(list(get_sonos_by_name()))))
        self._https.serve_url('/announcement_history', lambda: json.dumps(list(self._announcement_history)))
        self._https.serve_url('/svc_config', lambda: json.dumps({
            'https_server': self._https.server_url,
            'fuzzy_available': self._use_zmw_tts(),
        }))
        self._https.serve_url('/tts_languages', lambda: json.dumps(self._get_tts_languages()))

        # Start the HTTPS server (if certs available)
        self._https.start()
        if self._https.server_url:
            log.info("HTTPS server available at: %s", self._https.server_url)


    def _record_announcement(self, phrase, lang, volume, uri, fuzzy_text=None):
        entry = {
            'timestamp': datetime.now().isoformat(),
            'phrase': phrase,
            'lang': lang,
            'volume': volume,
            'uri': uri,
        }
        if fuzzy_text:
            entry['fuzzy_text'] = fuzzy_text
        self._announcement_history.append(entry)

    # --- ZMW TTS integration ---

    def _use_zmw_tts(self):
        """Whether zmw_text_to_speech should be attempted for synthesis."""
        if self._tts_mode == 'force_google_tts':
            return False
        if self._tts_mode == 'force_zmw_tts':
            return True
        return self._zmw_tts_voices is not None

    def _can_fallback_to_google(self):
        return self._tts_mode != 'force_zmw_tts'

    def _get_tts_languages(self):
        if self._use_zmw_tts():
            langs = []
            for v in self._zmw_tts_voices:
                entry = {"value": v["voice_id"], "label": f"{v['name']} ({v['locale']})"}
                if v.get("default_fallback"):
                    entry["default"] = True
                langs.append(entry)
            return langs
        return GOOGLE_TTS_LANGUAGES

    def on_dep_published_message(self, svc_name, subtopic, payload):
        if svc_name == 'ZmwTelegram' and subtopic.startswith("on_command/shout"):
            if 'cmd_args' not in payload:
                log.warning("ZmwTelegram::shout called with invalid payload: %s", payload)
                return
            txt = ' '.join(payload['cmd_args']).strip()
            if len(txt) == 0:
                log.warning("ZmwTelegram::shout called with no text: %s", payload)
                return
            # Run in a thread to avoid blocking the MQTT callback thread (would deadlock)
            threading.Thread(target=self._handle_shout, args=(txt,), daemon=True).start()
        self._rr.on_reply(subtopic, payload)

    def on_service_came_up(self, service_name):
        super().on_service_came_up(service_name)
        if service_name == "ZmwTextToSpeech" and self._tts_mode != 'force_google_tts':
            # Run in a thread to avoid blocking the MQTT callback thread (would deadlock)
            threading.Thread(target=self._fetch_zmw_tts_voices, daemon=True).start()
        if service_name == "ZmwTelegram":
            self.message_svc("ZmwTelegram",
                             "register_command", {'cmd': 'shout', 'descr': 'Announce something over speakers'})

    def _fetch_zmw_tts_voices(self, retries=3):
        """Request voice list from ZmwTextToSpeech, retrying to allow subscription to settle."""
        import time
        for attempt in range(retries):
            result = self._rr.request("ZmwTextToSpeech", "get_voices", {},
                                        "get_voices_reply", timeout=_ZMW_TTS_VOICES_TIMEOUT)
            if result is not None and len(result) > 0:
                self._zmw_tts_voices = result
                log.info("ZMW TTS available with %d voices", len(result))
                return
            if attempt < retries - 1:
                log.info("ZMW TTS get_voices attempt %d/%d failed, retrying...", attempt + 1, retries)
                time.sleep(2)
        log.warning("ZMW TTS get_voices returned no voices after %d attempts", retries)

    def _handle_shout(self, txt):
        try:
            vol = None
            local_path, tts_result = self._get_tts_asset(txt, lang_or_voice=None, fuzzy=True)
            remote_path = f"{self._public_tts_base}/{local_path}"
            fuzzy_text = tts_result.get('text') if tts_result and tts_result.get('fuzzy') else None
            self._record_announcement(txt, None, vol, remote_path, fuzzy_text=fuzzy_text)
            sonos_announce(remote_path, volume=vol, ws_api_cfg=self._cfg)
        except Exception:
            log.exception("Failed to handle shout: '%s'", txt)

    def _get_tts_asset(self, text, lang_or_voice, fuzzy=True):
        """Get a TTS mp3 asset. Returns (local_filename, tts_result_dict).

        When zmw_tts is active, lang_or_voice is a voice_id (from web) or language code (from MQTT).
        Falls back to Google TTS if zmw_tts fails and fallback is allowed.
        """
        if self._use_zmw_tts():
            local_fname, tts_result = self._request_zmw_tts(text, lang_or_voice, fuzzy=fuzzy)
            if local_fname:
                return local_fname, tts_result
            if self._can_fallback_to_google():
                log.warning("ZMW TTS failed for '%s', falling back to Google TTS", text)
                return get_local_path_tts(self._tts_assets_cache_path, text,
                                          self._cfg['tts_default_lang']), None
            raise RuntimeError("ZMW TTS failed and no fallback available")
        return get_local_path_tts(self._tts_assets_cache_path, text, lang_or_voice), None

    def _request_zmw_tts(self, text, lang_or_voice, fuzzy=True):
        """Send TTS request to ZmwTextToSpeech, copy result to local cache. Returns (filename, result) or (None, None)."""
        # If the value looks like a voice_id (contains '-'), use it as speaker;
        # otherwise treat it as a language code
        payload = {"text": text, "fuzzy": fuzzy}
        if lang_or_voice and '-' in lang_or_voice:
            payload["speaker"] = lang_or_voice
        elif lang_or_voice:
            payload["language"] = lang_or_voice

        result = self._rr.request("ZmwTextToSpeech", "tts", payload,
                                    "tts_reply", timeout=_ZMW_TTS_TIMEOUT)
        if not result or 'mp3_path' not in result:
            log.warning("Can't query ZMW TTS response is '%s'", result)
            return None, None

        mp3_path = result['mp3_path']
        if not os.path.isfile(mp3_path):
            log.warning("ZMW TTS returned path '%s' but file doesn't exist", mp3_path)
            return None, None

        fname = os.path.basename(mp3_path)
        dest = os.path.join(self._tts_assets_cache_path, fname)
        if mp3_path != dest:
            shutil.copy2(mp3_path, dest)
        return fname, result

    def get_mqtt_description(self):
        return {
            "description": "Text-to-speech announcements. Say a message out loud on speakers. Useful for calling people or announcing things. Broadcasts to all known Sonos speakers",
            "meta": self.get_service_meta(),
            "llm_skip_commands": ["ls"],
            "commands": {
                "ls": {
                    "description": "List speakers. Response on ls_reply",
                    "params": {}
                },
                "tts": {
                    "description": "Say a message out loud on speakers (text-to-speech). Use for announcements and notifications.",
                    "params": {
                        "msg": "Text to announce",
                        "lang?": "Language code",
                        "vol?": "Volume 0-100",
                        "fuzzy?": "Paraphrase text using voice personality before synthesis (default: true)",
                    }
                },
                "announcement_history": {
                    "description": "Get service history. Response on announcement_history_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Service definition",
                    "params": {}
                },
            },
            "announcements": {
                "ls_reply": {
                    "description": "List of speaker names",
                    "payload": ["speaker_name_1", "speaker_name_2"]
                },
                "tts_reply": {
                    "description": "Published when a TTS announcement completes. Contains generated asset paths",
                    "payload": {
                        "local_path": "Filename generated TTS audio",
                        "uri": "Public URL where TTS audio is served"
                    }
                },
                "announcement_history_reply": {
                    "description": "Announcement history",
                    "payload": [{"timestamp": "ISO timestamp", "phrase?": "Text", "lang": "Language", "volume": "Volume", "uri": "Asset URI"}]
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": "(this object)"
                },
            }
        }

    def _www_announce_tts(self):
        """Web endpoint for TTS announcements."""
        lang = request.args.get('lang', self._cfg['tts_default_lang'])
        vol = self._get_payload_vol(request.args)
        txt = request.args.get('phrase')
        fuzzy = request.args.get('fuzzy', 'true').lower() not in ('false', '0', 'no')
        speakers_param = request.args.get('speakers', '')
        speakers = [s.strip() for s in speakers_param.split(',') if s.strip()] if speakers_param else None
        if txt is None:
            return abort(400, "Message has no phrase")

        if speakers:
            log.info("Requested annoucement '%s' for speakers %s", txt, speakers)
        else:
            log.info("Requested annoucement '%s' in all speakers", txt)

        local_path, tts_result = self._get_tts_asset(txt, lang, fuzzy=fuzzy)
        remote_path = f"{self._public_tts_base}/{local_path}"
        fuzzy_text = tts_result.get('text') if tts_result and tts_result.get('fuzzy') else None
        self._record_announcement(txt, lang, vol, remote_path, fuzzy_text=fuzzy_text)
        sonos_announce(remote_path, volume=vol, ws_api_cfg=self._cfg, speakers=speakers)
        return {}

    def _announce_user_recording(self):
        """Handle user-recorded audio announcement."""
        if 'audio_data' not in request.files:
            return abort(400, "No audio_data in request")

        audio_file = request.files['audio_data']
        mp3_path = save_audio_as_mp3(audio_file, self._tts_assets_cache_path)
        if mp3_path is None:
            return abort(500, "Failed to convert audio")

        filename = os.path.basename(mp3_path)
        remote_path = f"{self._public_tts_base}/{filename}"

        vol = self._get_payload_vol(request.form)
        log.info("Saved recording to '%s' -> '%s'. Will announce at vol=%s", mp3_path, remote_path, vol)
        self._record_announcement('<user recording>', '', vol, remote_path)
        sonos_announce(remote_path, volume=vol, ws_api_cfg=self._cfg)
        return {}

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return
        match subtopic:
            case "ls":
                self.publish_own_svc_message("ls_reply", sorted(list(get_sonos_by_name())))
            case "tts":
                return self._tts_and_play(payload)
            case "play_asset":
                self._play_asset(payload)
            case "announcement_history":
                self.publish_own_svc_message("announcement_history_reply",
                    list(self._announcement_history))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.error("Unknown message %s payload %s", subtopic, payload)

    def _tts_and_play(self, payload):
        if 'msg' not in payload:
            log.error("Received request for tts, but payload has no msg")
            return
        # Run in a thread: _get_tts_asset may block waiting for a ZMW TTS MQTT reply,
        # and we can't block the MQTT callback thread (would deadlock)
        threading.Thread(target=self._tts_and_play_worker, args=(payload,), daemon=True).start()

    def _tts_and_play_worker(self, payload):
        lang = payload.get('lang', self._cfg['tts_default_lang'])
        fuzzy = bool(payload.get('fuzzy', True))
        try:
            local_path, tts_result = self._get_tts_asset(payload['msg'], lang, fuzzy=fuzzy)
        except RuntimeError:
            log.error("TTS failed for '%s'", payload['msg'], exc_info=True)
            return
        remote_path = f"{self._public_tts_base}/{local_path}"
        msg = {'local_path': local_path, 'uri': remote_path}
        self.publish_own_svc_message("tts_reply", msg)
        vol = self._get_payload_vol(payload)
        fuzzy_text = tts_result.get('text') if tts_result and tts_result.get('fuzzy') else None
        self._record_announcement(payload['msg'], lang, vol, remote_path, fuzzy_text=fuzzy_text)
        sonos_announce(remote_path, volume=vol, ws_api_cfg=self._cfg)

    def _save_asset_to_www(self, local_path):
        try:
            local_path = str(local_path)
            if not os.path.isfile(local_path):
                log.warning('Bad path to asset: "%s" is not a file', local_path)
                self.publish_own_svc_message("save_asset_reply",
                               {'status': 'error', 'cause': 'Bad path to asset "{local_path}"'})
                return None
            # If file existed, overwrite
            local_asset_path = shutil.copy2(local_path, self._tts_assets_cache_path)
        except OSError as e:
            log.error("Saving asset failed", exc_info=True)
            self.publish_own_svc_message("save_asset_reply", {'status': 'error', 'cause': str(e)})
            return None

        fname = os.path.basename(local_asset_path)
        asset_uri = f"{self._public_tts_base}/{fname}"
        log.info("Saved asset '%s' to '%s', available at uri '%s'", local_path, local_asset_path, asset_uri)
        self.publish_own_svc_message("save_asset_reply", {
            'status': 'ok',
            'asset': fname,
            'uri': asset_uri})
        return asset_uri

    def _play_asset(self, payload):
        srcs = 1 if 'name' in payload else 0
        srcs += 1 if 'local_path' in payload else 0
        srcs += 1 if 'public_www' in payload else 0
        if srcs != 1:
            log.error(
                "Request to play an asset must specifiy one and only one source "
                "out of name, local_path or public_www. Message: '%s'", str(payload))
            return

        asset_uri = None
        if 'local_path' in payload:
            asset_uri = self._save_asset_to_www(payload['local_path'])
        elif 'public_www' in payload:
            asset_uri = payload['public_www']
        else:
            asset_name = payload['name']
            asset_uri = f"{self._public_tts_base}/{asset_name}"
            local_path = os.path.join(self._tts_assets_cache_path, asset_name)
            if not os.path.isfile(local_path):
                log.error("Request to play an asset, but asset doesn't exist. Message: %s", str(payload))
                return

        if asset_uri is None:
            log.error("Failed to announce, MQTT payload: %s", str(payload))
            return

        vol = self._get_payload_vol(payload)
        log.info("Announcing asset %s with volume %d", asset_uri, vol)
        self._record_announcement('<asset playback>', '', vol, asset_uri)
        sonos_announce(asset_uri, volume=vol, ws_api_cfg=self._cfg)


    def _get_payload_vol(self, payload):
        vol = payload.get('vol', self._announce_vol)
        if vol == 'default':
            return self._announce_vol

        try:
            vol = int(vol)
        except (ValueError, TypeError):
            log.warning("Requested invalid volume '%s', using default announcement volume", vol)
            return self._announce_vol

        if vol < 0 or vol > 100:
            log.warning("Requested invalid volume '%d', using default announcement volume '%d'",
                        vol, self._announce_vol)
            return self._announce_vol
        return vol


service_runner(ZmwSpeakerAnnounce)
