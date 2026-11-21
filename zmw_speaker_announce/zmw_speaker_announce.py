"""MQTT speaker announcement service using Sonos."""
import difflib
import json
import re
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


def _norm_voice_name(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def _voice_aliases(voice):
    """Names a voice may be asked for by. Configured names have a description, eg 'GLaDOS (Murderous AI)',
    and voice_ids are like 'en_US-glados-high'."""
    name = voice['name']
    vid = voice['voice_id']
    aliases = {name, re.sub(r'\(.*?\)', '', name), name.split()[0] if name.split() else name, vid}
    vid_parts = vid.split('-')
    if len(vid_parts) >= 2:
        aliases.add(vid_parts[1])
    return {a for a in (_norm_voice_name(a) for a in aliases) if a}


def find_voice(voices, query):
    """Fuzzy search for a voice: exact alias, then unique substring, then closest spelling (for typos).
    Returns a voice_id, or None if nothing (or more than one voice) matches."""
    q = _norm_voice_name(query)
    if not q or not voices:
        return None
    aliases = {v['voice_id']: _voice_aliases(v) for v in voices}

    exact = [vid for vid, al in aliases.items() if q in al]
    if len(exact) == 1:
        return exact[0]
    if exact:
        log.warning("Voice '%s' is ambiguous: %s", query, exact)
        return None

    partial = [vid for vid, al in aliases.items() if any(q in a or a in q for a in al if len(a) > 2)]
    if len(partial) == 1:
        return partial[0]
    if partial:
        log.warning("Voice '%s' is ambiguous: %s", query, partial)
        return None

    alias_to_vid = {a: vid for vid, al in aliases.items() for a in al}
    close = difflib.get_close_matches(q, alias_to_vid.keys(), n=1, cutoff=0.75)
    return alias_to_vid[close[0]] if close else None

# Bot (LLM) announcements may be long reports: a 160 word report takes ~12s with a high quality voice, a
# max-length (2K, see zmw_telegram) message ~30s
_ZMW_TTS_BOT_TIMEOUT = 60
_ZMW_TTS_VOICES_TIMEOUT = 2
_HOMEBOARD_LS_TIMEOUT = 2


class ZmwSpeakerAnnounce(ZmwMqttService):
    """MQTT proxy for Sonos speaker announcements."""
    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_speaker_announce", scheduler=_sched,
                         svc_deps=["ZmwTextToSpeech", "ZmwTelegram", "ZmwHomeboard"])
        self._cfg = cfg
        self._announce_vol = cfg['announce_volume']
        self._announcement_history = deque(maxlen=10)

        # TTS mode: "auto" (default), "force_google_tts", "force_zmw_tts"
        self._tts_mode = cfg.get('tts_mode', 'auto')
        self._zmw_tts_voices = None
        # Ids of the homeboards that can play audio, kept up to date by ZmwHomeboard's audio_targets
        self._homeboard_audio_targets = []

        self._rr = MqttRequestReply(self.message_svc)

        # Save cache path for tts and register it as a www dir, to serve assets
        self._tts_assets_cache_path = cfg['tts_assets_cache_path']
        os.makedirs(self._tts_assets_cache_path, exist_ok=True)

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
        self._https.serve_url('/ls_speakers', lambda: json.dumps([t['name'] for t in self._list_speakers()]))
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


    def _record_announcement(self, phrase, lang, volume, uri, *, source, tts_result=None, speakers=None,
                             notify=True):
        """source is who asked for it: mqtt, http, telegram_user or telegram_bot. tts_result is what
        _get_tts_asset returned, for TTS announcements. speakers is what was requested (None: all)."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'source': source,
            'phrase': phrase,
            'lang': lang,
            'voice': tts_result.get('voice_id') if tts_result else None,
            'volume': volume,
            'uri': uri,
        }
        fuzzy_text = tts_result.get('text') if tts_result and tts_result.get('fuzzy') else None
        if fuzzy_text:
            entry['fuzzy_text'] = fuzzy_text
        self._announcement_history.append(entry)

        # Broadcast the spoken text as the announcement starts playing, so other
        # services (e.g. ZmwHomeboard) can mirror it, on the same speakers. Only
        # meaningful for TTS announcements; asset/recording playbacks pass notify=False.
        if notify:
            spoken = fuzzy_text or phrase
            if spoken:
                self.publish_own_svc_message("announcement_in_progress", {"msg": spoken, "speakers": speakers})

    def _homeboard_targets(self):
        """Ids of the homeboards that can play audio, or none while ZmwHomeboard is down."""
        if "ZmwHomeboard" not in self.get_known_services():
            return []
        return list(self._homeboard_audio_targets)

    def _list_speakers(self):
        """Every announcement target: [{'name': ..., 'kind': 'sonos' | 'homeboard'}]. Slow (Sonos discovery), and
        waits for ZmwHomeboard: don't call from the MQTT thread."""
        if "ZmwHomeboard" in self.get_known_services():
            # Asking is what makes ZmwHomeboard drop homeboards that have been offline for too long
            self._fetch_homeboard_audio_targets(retries=1)
        sonos = [{'name': n, 'kind': 'sonos'} for n in sorted(get_sonos_by_name())]
        homeboards = [{'name': n, 'kind': 'homeboard'} for n in sorted(self._homeboard_targets())]
        return sonos + homeboards

    def _announce(self, uri, vol, speakers=None, msg=None, *, synced):
        """Play uri on the speakers, and broadcast what's being played so other services can react.
        speakers are Sonos names and homeboard ids; None plays on all of them. msg is the text a TTS
        request asked to say; None for recordings and assets. synced trades latency for better playback
        sync between Sonos speakers (a skew is very noticeable in TTS); homeboards can't be synced."""
        all_homeboards = self._homeboard_targets()
        if speakers is None:
            sonos, homeboards = None, all_homeboards
        else:
            # Homeboard ids are generated from free text device names: don't make callers match their case
            hb_by_lower = {hb.lower(): hb for hb in all_homeboards}
            homeboards = [hb_by_lower[s.lower()] for s in speakers if s.lower() in hb_by_lower]
            sonos = [s for s in speakers if s.lower() not in hb_by_lower]

        playing = {
            'uri': uri,
            'volume': vol,
            'speakers': speakers,
        }
        if msg:
            playing['msg'] = msg
        self.publish_own_svc_message("currently_playing", playing)

        # Before Sonos, which blocks until it's playing
        for hb_id in homeboards:
            cmd = {'homeboard_id': hb_id, 'uri': uri}
            if vol is not None:
                cmd['volume'] = vol
            if msg:
                cmd['msg'] = msg
            try:
                self.message_svc("ZmwHomeboard", "announce_audio", cmd)
            except RuntimeError:
                log.warning("Can't announce on homeboard '%s', ZmwHomeboard is down", hb_id)

        # An empty list would mean every Sonos to sonos_announce
        if sonos is None or sonos:
            sonos_announce(uri, volume=vol, ws_api_cfg=self._cfg, speakers=sonos, synced=synced)

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
        if svc_name == 'ZmwTelegram' and subtopic in ("on_command/shout", "on_command/bot_shout"):
            if 'cmd_args' not in payload:
                log.warning("ZmwTelegram::%s called with invalid payload: %s", subtopic, payload)
                return
            if subtopic == "on_command/bot_shout":
                txt, voice, speakers = self._parse_bot_shout(payload['cmd_args'])
                # Bot messages are already LLM-written, don't paraphrase. Never fall back to Google TTS
                kwargs = {'voice': voice, 'speakers': speakers, 'fuzzy': False, 'is_bot': True}
            else:
                txt, kwargs = ' '.join(payload['cmd_args']).strip(), {}
            if len(txt) == 0:
                log.warning("ZmwTelegram::%s called with no text: %s", subtopic, payload)
                return
            # Run in a thread to avoid blocking the MQTT callback thread (would deadlock)
            threading.Thread(target=self._handle_shout, args=(txt,), kwargs=kwargs, daemon=True).start()
        if svc_name == 'ZmwTelegram' and subtopic == "on_command/bot_shout_voices":
            threading.Thread(target=self._bot_reply_voices, daemon=True).start()
        if svc_name == 'ZmwTelegram' and subtopic == "on_command/bot_shout_speakers":
            # Speaker discovery is slow, don't block the MQTT thread
            threading.Thread(target=self._bot_reply_speakers, daemon=True).start()
        if svc_name == 'ZmwHomeboard' and subtopic == "audio_targets":
            self._set_homeboard_audio_targets(payload)
        self._rr.on_reply(subtopic, payload)

    def on_service_came_up(self, service_name):
        super().on_service_came_up(service_name)
        if service_name == "ZmwTextToSpeech":
            # Fetch voices even in force_google_tts mode: bot commands always use ZMW TTS
            # Run in a thread to avoid blocking the MQTT callback thread (would deadlock)
            threading.Thread(target=self._fetch_zmw_tts_voices, daemon=True).start()
        if service_name == "ZmwHomeboard":
            # audio_targets only says when it changes: ask for the current list
            threading.Thread(target=self._fetch_homeboard_audio_targets, daemon=True).start()
        if service_name == "ZmwTelegram":
            self.message_svc("ZmwTelegram",
                             "register_command", {'cmd': 'shout', 'descr': 'Announce something over speakers'})
            # Commands for bots (eg an LLM), named /bot_[service]_[command]
            self.message_svc("ZmwTelegram", "register_command", {
                'cmd': 'bot_shout',
                'descr': 'Announce over speakers, args as JSON: {"msg": "text", "voice?": "name", '
                         '"speakers?": ["name", ...]}. See bot_shout_voices and bot_shout_speakers'})
            self.message_svc("ZmwTelegram", "register_command", {
                'cmd': 'bot_shout_voices', 'descr': 'List voices for bot_shout, as JSON'})
            self.message_svc("ZmwTelegram", "register_command", {
                'cmd': 'bot_shout_speakers', 'descr': 'List speakers for bot_shout, as JSON'})

    def _set_homeboard_audio_targets(self, homeboards):
        if not isinstance(homeboards, list) or not all(isinstance(hb, str) for hb in homeboards):
            log.warning("ZmwHomeboard sent bad audio targets: %s", homeboards)
            return
        if homeboards != self._homeboard_audio_targets:
            log.info("Homeboards that can play audio: %s", homeboards)
        self._homeboard_audio_targets = homeboards

    def _fetch_homeboard_audio_targets(self, retries=3):
        """Request the audio-capable homeboards, retrying to allow subscription to settle."""
        import time
        for attempt in range(retries):
            result = self._rr.request("ZmwHomeboard", "ls_audio_targets", {},
                                      "ls_audio_targets_reply", timeout=_HOMEBOARD_LS_TIMEOUT)
            if result is not None:
                self._set_homeboard_audio_targets(result)
                return
            if attempt < retries - 1:
                time.sleep(2)
        log.warning("ZmwHomeboard ls_audio_targets got no reply after %d attempts", retries)

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

    def _find_zmw_tts_voice(self, name):
        """Returns the voice_id for a voice name (eg 'glados') or voice_id, or None if not a known voice."""
        return find_voice(self._zmw_tts_voices, name)

    def _parse_bot_shout(self, cmd_args):
        """Parse '/bot_shout {"msg": "text", "voice": "name", "speakers": ["spk1", "spk2"]}'. voice and
        speakers are optional; an unknown voice falls back to the default one. Returns (txt, voice, speakers),
        txt is empty if the request is invalid."""
        # Telegram splits args on ' ', so joining them back gives the original JSON
        try:
            args = json.loads(' '.join(cmd_args))
        except json.JSONDecodeError:
            log.warning("ZmwTelegram::bot_shout called with invalid JSON: %s", cmd_args)
            return '', None, None
        if not isinstance(args, dict) or not isinstance(args.get('msg'), str):
            log.warning("ZmwTelegram::bot_shout needs a JSON object with a msg, got: %s", args)
            return '', None, None

        voice = None
        if args.get('voice'):
            voice = self._find_zmw_tts_voice(str(args['voice']))
            if voice is None:
                log.warning("ZmwTelegram::bot_shout requested unknown voice '%s', using default", args['voice'])

        speakers = args.get('speakers')
        if isinstance(speakers, str):
            speakers = [speakers]
        if not isinstance(speakers, list):
            speakers = None
        speakers = [str(s).strip() for s in speakers if str(s).strip()] if speakers else None
        return args['msg'].strip(), voice, speakers or None

    def _bot_reply_voices(self):
        if not self._zmw_tts_voices:
            # Maybe ZmwTextToSpeech wasn't up when we started
            self._fetch_zmw_tts_voices(retries=1)
        if not self._zmw_tts_voices:
            self.message_svc("ZmwTelegram", "send_text", {'msg': 'bot_shout_voices: ZmwTextToSpeech unavailable'})
            return
        voices = [{'voice': v['name'], 'locale': v['locale']} for v in self._zmw_tts_voices]
        self.message_svc("ZmwTelegram", "send_text", {'msg': json.dumps(voices)})

    def _bot_reply_speakers(self):
        self.message_svc("ZmwTelegram", "send_text", {'msg': json.dumps(self._list_speakers())})

    def _handle_shout(self, txt, voice=None, speakers=None, fuzzy=True, is_bot=False):
        """Announce txt. voice=None uses the default TTS voice, speakers=None announces on all speakers.
        is_bot: request from a bot, may be long and must use ZMW TTS (never fall back to Google TTS)."""
        try:
            vol = self._announce_vol
            log.info("Shout '%s' with voice %s on speakers %s", txt, voice or 'default', speakers or 'all')
            if is_bot:
                local_path, tts_result = self._get_tts_asset(txt, lang_or_voice=voice, fuzzy=fuzzy,
                                                             zmw_tts_only=True, timeout=_ZMW_TTS_BOT_TIMEOUT)
            else:
                local_path, tts_result = self._get_tts_asset(txt, lang_or_voice=voice, fuzzy=fuzzy)
            remote_path = f"{self._public_tts_base}/{local_path}"
            self._record_announcement(txt, voice, vol, remote_path, tts_result=tts_result, speakers=speakers,
                                      source='telegram_bot' if is_bot else 'telegram_user')
            self._announce(remote_path, vol, speakers=speakers, msg=txt, synced=True)
        except Exception as ex:
            log.exception("Failed to handle shout: '%s'", txt)
            if is_bot:
                self.message_svc("ZmwTelegram", "send_text", {'msg': f"bot_shout failed: {ex}"})

    def _get_tts_asset(self, text, lang_or_voice, fuzzy=True, zmw_tts_only=False, timeout=_ZMW_TTS_TIMEOUT):
        """Get a TTS mp3 asset. Returns (local_filename, tts_result_dict). tts_result_dict is ZmwTextToSpeech's
        reply, or only {'voice_id': 'google_tts:<lang>'} for Google TTS.

        When zmw_tts is active, lang_or_voice is a voice_id (from web) or language code (from MQTT).
        Falls back to Google TTS if zmw_tts fails and fallback is allowed. zmw_tts_only overrides
        tts_mode: always use zmw_tts and never fall back.
        """
        if zmw_tts_only or self._use_zmw_tts():
            local_fname, tts_result = self._request_zmw_tts(text, lang_or_voice, fuzzy=fuzzy, timeout=timeout)
            if local_fname:
                return local_fname, tts_result
            if not zmw_tts_only and self._can_fallback_to_google():
                log.warning("ZMW TTS failed for '%s', falling back to Google TTS", text)
                lang = self._cfg['tts_default_lang']
                return get_local_path_tts(self._tts_assets_cache_path, text, lang), {'voice_id': f'google_tts:{lang}'}
            raise RuntimeError("ZMW TTS failed and no fallback available")
        return (get_local_path_tts(self._tts_assets_cache_path, text, lang_or_voice),
                {'voice_id': f'google_tts:{lang_or_voice}'})

    def _request_zmw_tts(self, text, lang_or_voice, fuzzy=True, timeout=_ZMW_TTS_TIMEOUT):
        """Send TTS request to ZmwTextToSpeech, copy result to local cache. Returns (filename, result) or (None, None)."""
        # If the value looks like a voice_id (contains '-'), use it as speaker;
        # otherwise treat it as a language code
        payload = {"text": text, "fuzzy": fuzzy}
        if lang_or_voice and '-' in lang_or_voice:
            payload["speaker"] = lang_or_voice
        elif lang_or_voice:
            payload["language"] = lang_or_voice

        result = self._rr.request("ZmwTextToSpeech", "tts", payload,
                                    "tts_reply", timeout=timeout)
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
            "description": "Text-to-speech announcements. Say a message out loud on speakers. Useful for calling people or announcing things. Plays on all Sonos speakers and audio-capable homeboards, or on the ones requested",
            "meta": self.get_service_meta(),
            # MQTT data flow; feeds the map in the top-level README (scripts/build_mqtt_map.py).
            # Reads: /shout commands, and which homeboards can play audio. (ZmwTextToSpeech is request/reply
            # only, so not a read.)
            "reads_mqtt_topic": ["zmw_telegram", "zmw_homeboard"],
            # Writes: synthesis requests, registering the /shout commands, and announce_audio to homeboards.
            "writes_mqtt_topic": ["zmw_text_to_speech", "zmw_telegram", "zmw_homeboard"],
            "llm_skip_commands": ["ls"],
            "commands": {
                "ls": {
                    "description": "List speakers (Sonos and homeboards that can play audio). Response on ls_reply",
                    "params": {}
                },
                "tts": {
                    "description": "Say a message out loud on speakers (text-to-speech). Use for announcements and notifications.",
                    "params": {
                        "msg": "Text to announce",
                        "lang?": "Language code",
                        "vol?": "Volume 0-100",
                        "fuzzy?": "Paraphrase text using voice personality before synthesis (default: true)",
                        "speakers?": "List of speaker names, Sonos or homeboard (see ls). Default: all speakers",
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
                    "description": "List of speaker names: Sonos speakers, then homeboard ids",
                    "payload": ["speaker_name_1", "speaker_name_2"]
                },
                "tts_reply": {
                    "description": "Published when a TTS announcement completes. Contains generated asset paths",
                    "payload": {
                        "local_path": "Filename generated TTS audio",
                        "uri": "Public URL where TTS audio is served"
                    }
                },
                "announcement_in_progress": {
                    "description": "Published when a spoken (TTS) announcement starts playing on the speakers. Lets other services mirror the announced text, on the same speakers",
                    "payload": {"msg": "The text being announced",
                                "speakers": "Requested speaker names, Sonos or homeboard (null: all speakers)"}
                },
                "currently_playing": {
                    "description": "Published whenever the speakers are asked to play a sound (TTS, user recording or asset)",
                    "payload": {
                        "uri": "URL of the audio being played",
                        "volume": "Requested volume 0-100 (null: speaker default)",
                        "speakers": "List of target speaker names, Sonos or homeboard (null: all speakers)",
                        "msg?": "Original text of the TTS request; absent for recordings and assets",
                    }
                },
                "announcement_history_reply": {
                    "description": "Announcement history",
                    "payload": [{"timestamp": "ISO timestamp",
                                 "source": "Who requested it: mqtt, http, telegram_user or telegram_bot",
                                 "phrase?": "Text", "lang": "Requested language or voice",
                                 "voice": "Voice used (ZMW TTS voice_id, or google_tts:<lang>); null if not TTS",
                                 "volume": "Volume", "uri": "Asset URI"}]
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
        self._record_announcement(txt, lang, vol, remote_path, tts_result=tts_result, speakers=speakers,
                                  source='http')
        self._announce(remote_path, vol, speakers=speakers, msg=txt, synced=True)
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
        self._record_announcement('<user recording>', '', vol, remote_path, source='http', notify=False)
        self._announce(remote_path, vol, synced=False)
        return {}

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return
        match subtopic:
            case "ls":
                # Waits for ZmwHomeboard, can't block the MQTT callback thread (would deadlock)
                threading.Thread(target=lambda: self.publish_own_svc_message(
                    "ls_reply", [t['name'] for t in self._list_speakers()]), daemon=True).start()
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
            case "announcement_in_progress" | "currently_playing":
                # Echo of our own broadcasts (published for other services to
                # mirror). Ignore them.
                return
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
        speakers = payload.get('speakers')
        if isinstance(speakers, str):
            speakers = [speakers]
        if not isinstance(speakers, list):
            speakers = None
        speakers = [str(s).strip() for s in speakers if str(s).strip()] if speakers else None
        self._record_announcement(payload['msg'], lang, vol, remote_path, tts_result=tts_result,
                                  speakers=speakers, source='mqtt')
        self._announce(remote_path, vol, speakers=speakers, msg=payload['msg'], synced=True)

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
        self._record_announcement('<asset playback>', '', vol, asset_uri, source='mqtt', notify=False)
        self._announce(asset_uri, vol, synced=False)


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
