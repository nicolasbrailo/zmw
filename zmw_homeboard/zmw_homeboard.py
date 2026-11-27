import json
import os
import pathlib
import re
import tempfile
import threading
import time
from datetime import datetime, timedelta

from flask import Response, abort, request, send_from_directory

from zzmw_lib.logs import build_logger
from zzmw_lib.meteo_relay_client import METEO_RELAY_SVC, get_weather_from_relay
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from homeboard_janitor import HomeboardJanitor, is_gone
from homeboard_mqtt import HomeboardMqtt, as_year
from immich_thumbs import ImmichThumbs, as_asset_id

from announce_overlay import AnnounceOverlay
from overlay import Overlay
from qr_overlay import QrOverlay
from weather_overlay import WeatherOverlay

log = build_logger("ZmwHomeboard")

# Refresh cadence and the timeout we push to the homeboard. If the service
# dies between cron ticks the overlay self-clears.
_OVERLAY_REFRESH_SECS = 60 * 60

# Hours during which the weather panel is shown.
_WEATHER_HOURS = range(7, 23)        # 07:00 – 22:59
# Hours during which the overlay stays cleared unless an announcement is
# active. The 23:00 cron does the initial clear; recomputes during these
# hours produce an empty overlay so any extra trigger doesn't bring it back.
_OVERLAY_OFF_HOURS = set(range(0, 7)) | {23}

_QR_URL_TEMPLATE = "{www_url}/index.html?hb_id={hb_id}"

# How long a mirrored speaker announcement stays on the overlay, in seconds.
_SPEAKER_ANNOUNCE_OVERLAY_SECS = 60

# An audio-capable homeboard that goes offline stays an audio target for this long: devices drop off the broker
# and reconnect often, and the list shouldn't flap with them. Only checked when the list is needed.
_AUDIO_TARGET_OFFLINE_TTL_SECS = 10 * 60


def can_play_audio(host_info):
    """Whether a homeboard plays announce_audio, going by its availability record.

    Devices that can say so with an `announce_audio` flag (AstroDock, on Portals, sets it from its "Play audio
    announcements" switch). Without it (eg the Raspberry Pi homeboards) there's no audio.
    """
    return host_info.get('announce_audio') is True


# How many wake word recordings are kept
_WAKEWORD_KEEP = 50


# What a recording's file is called: mkstemp's names, which is all the download route serves
_WAKEWORD_FILE_RE = re.compile(r'^[A-Za-z0-9_-]+\.wav$')


def _wakeword_recordings(wakeword_dir):
    """The recordings in wakeword_dir, newest first, as DirEntry."""
    return sorted((e for e in os.scandir(wakeword_dir) if e.is_file() and _WAKEWORD_FILE_RE.match(e.name)),
                  key=lambda e: e.stat().st_mtime, reverse=True)


def _wakeword_meta_path(wav_path):
    """Where what we know about a recording is kept: next to it, same name, .json."""
    return wav_path[:-len('.wav')] + '.json'


def _prune_wakeword_dir(wakeword_dir):
    """Drops all but the newest _WAKEWORD_KEEP recordings, so the dir doesn't fill up."""
    try:
        files = _wakeword_recordings(wakeword_dir)
    except OSError:
        log.warning("Can't list %s", wakeword_dir, exc_info=True)
        return
    for old in files[_WAKEWORD_KEEP:]:
        for path in (old.path, _wakeword_meta_path(old.path)):
            try:
                os.remove(path)
            except FileNotFoundError:
                # Recordings saved before their metadata was, have none
                pass
            except OSError:
                log.warning("Can't remove old wake word recording %s", path, exc_info=True)


class ZmwHomeboard(ZmwMqttService):
    """
    Bridge between the homeboard MQTT broker and the ZMW bus.

    Uses homeboard_mqtt.HomeboardMqtt to talk to homeboards. Republishes
    selected homeboard state onto the ZMW bus so other ZMW services can
    consume it. Accepts ZMW-bus commands and forwards them to
    the target homeboard. Composes per-homeboard SVG overlays (weather +
    QR + announcements) and pushes them via set_svg_overlay.
    """

    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_homeboard", scheduler=_sched,
                         svc_deps=["ZmwSpeakerAnnounce", "ZmwDoorman", METEO_RELAY_SVC,
                                   "ZmwSpeechToText"])

        self._sched = _sched
        # The weather panel shows the relay's default location (the house). The relay asks Open-Meteo with
        # timezone=auto, so the forecast is in the location's local time.
        if cfg.get('weather'):
            log.warning("Config 'weather' is ignored: the weather panel shows %s's default location, set it in that "
                        "service's config", METEO_RELAY_SVC)
        self._weather = WeatherOverlay(
            "weather_icons",
            get_weather=lambda: get_weather_from_relay(self, client='zmw_homeboard'),
        )
        self._qr = QrOverlay()
        self._announce = AnnounceOverlay()

        # hb_id -> (text, expires_at_ts). Only kept while the announce is live.
        self._announce_state = {}

        # The album filter last pushed to every homeboard, or None if we haven't
        # set one since this service started. There is one filter for all of
        # them, like announcements: the homeboards persist it themselves, so
        # this is only what we last asked for, not what they're running. It's
        # re-sent to each board that comes online, in case it missed it.
        self._album_filter = None

        # hb_id -> what we last republished on the ZMW bus from its state
        # record, per subtopic. Only touched from the MQTT loop thread.
        self._republished = {}

        # The homeboards that can play audio, as last published on audio_targets,
        # and since when each offline homeboard has been offline. Used from both
        # MQTT loop threads, under the lock.
        self._audio_targets_lock = threading.Lock()
        self._published_audio_targets = None
        self._offline_since = {}

        # Registered before the MQTT link starts: its callbacks build overlays,
        # and the overlay's QR code points at this UI.
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

        # Where wake word recordings go. Used to share WW audio with transcription service
        self._wakeword_dir = os.path.abspath(cfg['wakeword_dir'])

        # Where the UI's thumbnails of the pictures on screen come from
        self._thumbs = ImmichThumbs(cfg['immich']['url'], cfg['immich']['api_key'])

        self._core = HomeboardMqtt(
            cfg['homeboard']['mqtt_ip'],
            int(cfg['homeboard']['mqtt_port']),
            on_device_state=self._on_hb_device_state,
            on_host_info=self._on_hb_host_info,
            on_online=self._on_hb_online,
            on_wakeword_recording=self._on_hb_wakeword_recording,
        )
        self._core.start()

        www.serve_url('/get_homeboards_state', self._get_homeboards_state)
        www.serve_url('/thumbnail_immich/<asset_id>', self._www_thumbnail_immich)
        # The wake word page (wakeword.html), for debugging
        www.serve_url('/wakeword/ls', self._www_wakeword_ls)
        www.serve_url('/wakeword/file/<name>', self._www_wakeword_file)
        # Per-homeboard controls for the www UI. Each maps to the same command
        # the MQTT interface offers, so both routes behave identically.
        www.serve_url('/cmd/<hb_id>/next', self._www_next)
        www.serve_url('/cmd/<hb_id>/prev', self._www_prev)
        www.serve_url('/cmd/<hb_id>/force_on', self._www_force_on)
        www.serve_url('/cmd/<hb_id>/force_off', self._www_force_off)
        www.serve_url('/cmd/<hb_id>/set_transition_time_secs/<int:secs>',
                      self._www_set_transition_time_secs)
        # One announcement goes to every homeboard at once
        www.serve_url('/announce_all', self._www_announce_all, methods=['PUT'])
        # Same for the album filter: one filter, pushed to all of them
        www.serve_url('/set_album_filter_all', self._www_set_album_filter_all,
                      methods=['PUT'])

        _sched.add_job(self._recompute_all_overlays,
                       trigger='cron', hour='7-22', minute=0)
        _sched.add_job(self._clear_all_overlays,
                       trigger='cron', hour=23, minute=0)
        self._janitor = HomeboardJanitor(self._core, _sched)

    def _audio_targets(self):
        """Ids of the homeboards that can play audio announcements: online, or offline for less than
        _AUDIO_TARGET_OFFLINE_TTL_SECS. Called whenever the list is needed, which is also when homeboards
        that have been offline for too long drop out of it: audio_targets is published if the list changed."""
        now = time.time()
        with self._audio_targets_lock:
            targets = []
            for hb in self._core.list_homeboards():
                if not can_play_audio(hb.get('host_info') or {}):
                    continue
                if hb['state'] == 'online':
                    self._offline_since.pop(hb['id'], None)
                elif now - self._offline_since.setdefault(hb['id'], now) > _AUDIO_TARGET_OFFLINE_TTL_SECS:
                    continue
                targets.append(hb['id'])

            if targets == self._published_audio_targets:
                return targets
            self._published_audio_targets = targets
        log.info("Homeboards that can play audio: %s", targets)
        self.publish_own_svc_message('audio_targets', targets)
        return targets

    def _active_homeboards(self):
        """Homeboards worth composing/pushing overlays to.

        list_homeboards() already excludes availability records the core couldn't
        parse (bad format). On top of that, we drop boards that are gone, so
        we stop pushing at them before the janitor clears their record.
        """
        now = time.time()
        return [hb for hb in self._core.list_homeboards() if not is_gone(hb, now)]

    def _now_hour(self):
        return datetime.now().hour

    def _is_overlay_off(self):
        return self._now_hour() in _OVERLAY_OFF_HOURS

    def _is_weather_hour(self):
        return self._now_hour() in _WEATHER_HOURS

    def _get_announce(self, hb_id):
        state = self._announce_state.get(hb_id)
        if not state:
            return None, None
        text, expires_at = state
        if expires_at is not None and time.time() >= expires_at:
            del self._announce_state[hb_id]
            return None, None
        return text, expires_at

    def _build_overlay_for(self, hb):
        """Build (overlay, weather_failed) for one homeboard."""
        overlay = Overlay(hb.get('host_info', {}))
        weather_failed = False

        text, _expires = self._get_announce(hb['id'])

        # Off hours: only show the overlay when there's an active announce.
        if self._is_overlay_off() and not text:
            return overlay, weather_failed

        if self._is_weather_hour():
            try:
                weather_frag = self._weather.build_fragment()
            except Exception:
                log.exception("Weather build_fragment raised for %s", hb['id'])
                weather_frag = None
            if weather_frag is None:
                weather_failed = True
            overlay.add(weather_frag)

        try:
            qr_frag = self._qr.build_fragment(_QR_URL_TEMPLATE.format(www_url=self._public_url_base, hb_id=hb['id']))
            overlay.add(qr_frag)
        except Exception:
            log.exception("QR build_fragment raised for %s", hb['id'])

        if text:
            try:
                logical_w, _ = overlay.logical_size
                announce_frag = self._announce.build_fragment(
                    text, canvas_width=logical_w)
                overlay.add(announce_frag)
            except Exception:
                log.exception("Announce build_fragment raised for %s", hb['id'])

        return overlay, weather_failed

    def _push_overlay_for(self, hb):
        """Compose + push the overlay for one homeboard. Returns weather_failed."""
        overlay, weather_failed = self._build_overlay_for(hb)
        svg = overlay.compose() or ''

        # Push timeout = min over fragment lifetimes so that if the service
        # dies, the homeboard naturally drops the overlay. Announce expiry
        # tightens the timeout when an announce is active.
        timeout = _OVERLAY_REFRESH_SECS
        _text, expires_at = self._get_announce(hb['id'])
        if expires_at is not None:
            remaining = max(1, int(expires_at - time.time()))
            timeout = min(timeout, remaining)

        self._core.set_svg_overlay(hb['id'], timeout_secs=timeout, svg=svg)
        log.info("Pushed overlay for %s (timeout=%ss, weather_ok=%s)",
                 hb['id'], timeout, not weather_failed)
        return weather_failed

    def _recompute_overlay_for(self, hb_id):
        for hb in self._active_homeboards():
            if hb['id'] == hb_id:
                try:
                    self._push_overlay_for(hb)
                except Exception:
                    log.exception("Overlay push raised for %s", hb_id)
                return
        log.warning("Cannot recompute overlay for unknown homeboard '%s'", hb_id)

    def _recompute_all_overlays(self, scheduled=True):
        if self._is_overlay_off():
            log.info("Overlay off-hours; skipping recompute")
            return

        targets = self._active_homeboards()
        log.info("Recomputing overlays for %s homeboards", len(targets))
        any_weather_failed = False
        for hb in targets:
            try:
                if self._push_overlay_for(hb):
                    any_weather_failed = True
            except Exception:
                log.exception("Overlay push raised for %s", hb['id'])

        if any_weather_failed and scheduled and self._is_weather_hour():
            log.info("Weather failed (network?), retrying recompute in 60s")
            self._sched.add_job(self._recompute_all_overlays,
                                args=[False],
                                trigger='date',
                                run_date=datetime.now() + timedelta(seconds=60))

    def _clear_all_overlays(self):
        targets = self._active_homeboards()
        log.info("Clearing overlays for %s homeboards", len(targets))
        for hb in targets:
            try:
                self._core.set_svg_overlay(hb['id'], timeout_secs=0, svg='')
            except Exception:
                log.exception("Clear overlay raised for %s", hb['id'])

    def _set_announce(self, hb_id, text, timeout_secs):
        text = (text or '').strip()
        if not text:
            self._announce_state.pop(hb_id, None)
            self._recompute_overlay_for(hb_id)
            return True

        timeout_secs = max(1, int(timeout_secs))
        self._announce_state[hb_id] = (text, time.time() + timeout_secs)
        # Recompute when the announce expires so the overlay gets re-pushed
        # without it (and without waiting for the next cron tick).
        self._sched.add_job(self._recompute_overlay_for,
                            args=[hb_id],
                            trigger='date',
                            run_date=datetime.now() + timedelta(seconds=timeout_secs))
        self._recompute_overlay_for(hb_id)
        return True

    @staticmethod
    def _parse_album_filter(req):
        """Validate an album filter request. Returns (filter, error_description).

        The four fields are all optional, and an absent one means "no
        constraint of that kind" rather than "leave it as it was": the filter
        is always replaced whole, so an empty request is the way to clear it
        and show every album again.
        """
        filt = {}
        for key in ('name', 'exclude'):
            val = req.get(key) or ''
            if not isinstance(val, str):
                return None, f"{key} must be a string"
            filt[key] = val.strip()

        for key in ('from_year', 'to_year'):
            raw = req.get(key)
            # Absent, null, or an empty box in the UI all mean "unbounded"
            if raw is None or raw == '':
                raw = 0
            year = as_year(raw)
            if year is None:
                return None, f"{key} must be a whole number between 0 and 9999"
            filt[key] = year

        # The year test is an overlap test, so a reversed range isn't empty: it
        # selects the albums straddling the boundary, which looks exactly like
        # the filter being ignored. Refuse it instead.
        if filt['from_year'] and filt['to_year'] and filt['from_year'] > filt['to_year']:
            return None, "from_year cannot be later than to_year"

        return filt, None

    def _push_album_filter(self, filt):
        """Push one album filter to every homeboard. Returns (sent_to, failed)."""
        sent_to = []
        failed = []
        for hb in self._active_homeboards():
            if self._core.set_album_filter(hb['id'], **filt):
                sent_to.append(hb['id'])
            else:
                failed.append(hb['id'])
        # Remember what we asked for even if some boards didn't take it, so the
        # UI shows the filter that's meant to be in force.
        self._album_filter = filt
        log.info("Album filter %s pushed to %s homeboards", filt, len(sent_to))
        if failed:
            log.warning("Album filter push failed for %s", failed)
        return sent_to, failed

    def _on_hb_host_info(self, hb_id, _data):
        # Every availability record: a board going on/offline (noted, but only dropped from the list after a
        # while), or switching audio announcements on/off
        self._audio_targets()
        log.info("Config for '%s' changed, recomputing overlay", hb_id)
        # Recompute everyone: weather comes from ZmwMeteoRelay's cache, so
        # this is cheap unless we have many homeboards.
        self._recompute_all_overlays(scheduled=False)

    def _on_hb_wakeword_recording(self, hb_id, req):
        """Keep what a homeboard heard after its wake word. Saved for now, in the config's wakeword_dir.
        Runs on the homeboard broker's loop thread; the file is a few hundred KB at most.
        """
        try:
            os.makedirs(self._wakeword_dir, exist_ok=True)
            fd, path = tempfile.mkstemp(suffix='.wav', dir=self._wakeword_dir)
            with os.fdopen(fd, 'wb') as fp:
                fp.write(req['audio'])
            # The file name says nothing, so who said it and when goes next to it (for the wake word page)
            meta = {k: v for k, v in req.items() if k != 'audio'}
            meta.update({'hb_id': hb_id, 'received': time.time()})
            with open(_wakeword_meta_path(path), 'w', encoding='utf-8') as fp:
                json.dump(meta, fp)
        except OSError:
            log.error("Can't save wake word recording %s from '%s'", req['id'], hb_id, exc_info=True)
            return
        log.info("Saved wake word recording %s from '%s' to %s", req['id'], hb_id, path)
        _prune_wakeword_dir(self._wakeword_dir)
        # The result comes back as ZmwSpeechToText's transcription announcement, with this same path
        self.message_svc("ZmwSpeechToText", "transcribe", {"wav_path": path})

    def _on_stt_transcription(self, payload):
        """Send what ZmwSpeechToText understood of one of our recordings back to the homeboard that recorded it,
        and store it in the recording's metadata, for the wake word page.

        Every transcription is announced to everyone (Telegram voice messages too), so it's ours if its file is
        a recording in wakeword_dir: those names are unique, so the path says which one it is, and its metadata
        who asked. Requests in flight don't share anything else, so any number of them can be.
        """
        if not isinstance(payload, dict):
            return
        path = payload.get('file')
        if not isinstance(path, str) or os.path.dirname(os.path.abspath(path)) != self._wakeword_dir:
            return
        if not _WAKEWORD_FILE_RE.match(os.path.basename(path)) or not os.path.isfile(path):
            # Pruned meanwhile, or not a recording
            return
        meta_path = _wakeword_meta_path(path)
        try:
            with open(meta_path, encoding='utf-8') as fp:
                meta = json.load(fp)
        except (OSError, ValueError):
            meta = None
        if not isinstance(meta, dict):
            meta = {}
        text = payload.get('text')
        text = text.strip() if isinstance(text, str) else ''
        hb_id, req_id = meta.get('hb_id'), meta.get('id')
        log.info("Wake word recording %s from '%s' says: '%s'", req_id, hb_id, text)

        # First, so the device shows it as soon as possible; storing it is only for the page. Recordings saved
        # before their metadata was don't say who asked.
        if hb_id is None or req_id is None:
            log.warning("Can't send the transcription of %s back: its metadata doesn't say who asked", path)
        elif not self._core.voice_transcription(hb_id, req_id, text):
            log.warning("Can't send the transcription of request %s back to '%s'", req_id, hb_id)

        meta['transcription'] = {
            'text': text,
            'confidence': payload.get('confidence'),
            'ts': time.time(),
        }
        # Pruned while it was being transcribed: don't leave its metadata behind with no recording
        if not os.path.isfile(path):
            return
        # Replaced whole, so the page never reads half a file
        tmp_path = meta_path + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as fp:
                json.dump(meta, fp)
            os.replace(tmp_path, meta_path)
        except OSError:
            log.error("Can't save the transcription of %s", path, exc_info=True)

    def _on_hb_online(self, hb_id):
        """Re-send the config we hold to a homeboard that just (re)started.

        Commands aren't retained, so a board that was off when one was sent
        never got it. The overlay needs nothing here: _on_hb_host_info already
        pushes it on every availability record. Settings we only forward
        (transition time, embed QR, target size) aren't kept, so there's
        nothing to re-send for them.
        """
        filt = self._album_filter
        if filt is None:
            return
        log.info("Homeboard '%s' came online, re-sending album filter %s", hb_id, filt)
        if not self._core.set_album_filter(hb_id, **filt):
            log.warning("Re-sending album filter to '%s' failed", hb_id)

    def _on_hb_device_state(self, hb_id, record):
        """Republish parts of the state record for ZmwSensormon.

        The record changes whenever any part of it does, so each part is only
        republished when it changed, or sensormon would log the same reading
        over and over.
        """
        # Nulls are left out of the objects rather than passed on: sensormon
        # records whatever keys it finds, and would read an unknown `occupied`
        # as "empty".
        occ = record.get('occupancy')
        if isinstance(occ, dict):
            occ = {k: v for k, v in occ.items() if v is not None}
            self._republish_if_changed(hb_id, 'occupancy', occ)

        slideshow = record.get('slideshow')
        active = slideshow.get('active') if isinstance(slideshow, dict) else None
        if isinstance(active, bool):
            self._republish_if_changed(hb_id, 'slideshow_active', active)

        # Null on devices without one (a homeboard)
        battery = record.get('battery')
        if isinstance(battery, dict):
            battery = {k: v for k, v in battery.items() if v is not None}
            if battery:
                self._republish_if_changed(hb_id, 'battery', battery)

        for key in ('wifi_rssi', 'light_lux'):
            val = record.get(key)
            if val is not None:
                self._republish_if_changed(hb_id, key, val)

    def _republish_if_changed(self, hb_id, subtopic, payload):
        last = self._republished.setdefault(hb_id, {})
        if subtopic in last and last[subtopic] == payload:
            return
        last[subtopic] = payload
        self.publish_own_svc_message(f'{hb_id}/{subtopic}', payload)

    def on_service_came_up(self, service_name):
        super().on_service_came_up(service_name)
        if service_name == METEO_RELAY_SVC and self._is_weather_hour():
            # Overlays pushed before the relay was discovered have no weather panel; off the MQTT thread, since
            # fetching may block for a while
            log.info("%s is up, recomputing overlays", METEO_RELAY_SVC)
            self._sched.add_job(self._recompute_all_overlays, args=[False], trigger='date',
                                run_date=datetime.now() + timedelta(seconds=2))

    def on_dep_published_message(self, svc_name, subtopic, payload):
        # Mirror live speaker announcements onto the homeboard overlays: when
        # ZmwSpeakerAnnounce speaks something, show the same text as if 'announce'
        # had been called over MQTT for each homeboard. Only on the homeboards it
        # was targeted at, if it was targeted (speakers is null when it plays everywhere).
        if svc_name == "ZmwSpeakerAnnounce" and subtopic == "announcement_in_progress":
            if not isinstance(payload, dict):
                log.warning("ZmwSpeakerAnnounce announcement_in_progress with bad payload: %s", payload)
                return
            text = (payload.get('msg') or '').strip()
            if not text:
                return
            speakers = payload.get('speakers')
            targets = self._active_homeboards()
            if isinstance(speakers, list):
                # Same as ZmwSpeakerAnnounce, homeboard ids are matched regardless of case
                wanted = {s.lower() for s in speakers if isinstance(s, str)}
                targets = [hb for hb in targets if hb['id'].lower() in wanted]
            log.info("Mirroring speaker announcement onto homeboards %s: '%s'", [hb['id'] for hb in targets], text)
            for hb in targets:
                self._set_announce(hb['id'], text, _SPEAKER_ANNOUNCE_OVERLAY_SECS)

        # Audio isn't mirrored: ZmwSpeakerAnnounce sends announce_audio to the
        # homeboards it targets (see audio_targets)

        elif svc_name == "ZmwSpeechToText" and subtopic == "transcription":
            self._on_stt_transcription(payload)

        # Someone rang: every homeboard gets the ring, with the door's streams so it can show who's there
        elif svc_name == "ZmwDoorman" and subtopic == "on_doorbell_ring":
            if not isinstance(payload, dict):
                log.warning("ZmwDoorman on_doorbell_ring with bad payload: %s", payload)
                return
            rtsp_urls = payload.get('rtsp_urls') or {}
            log.info("Doorbell rang, notifying homeboards (streams: %s)", list(rtsp_urls))
            failed = []
            for hb in self._active_homeboards():
                if not self._core.doorbell_ring(hb['id'], rtsp_urls):
                    failed.append(hb['id'])
            if failed:
                log.warning("doorbell_ring failed for %s", failed)

    def get_service_alerts(self):
        if self._core.is_connected():
            return []
        ip, port = self._core.broker
        return [f"Homeboard MQTT broker [{ip}]:{port} is not reachable"]

    def _get_homeboards_state(self):
        return {
            "broker_connected": self._core.is_connected(),
            "homeboards": self._core.list_homeboards(),
            "album_filter": self._album_filter,
        }

    # ---- WWW UI ----------------------------------------------------------

    def _www_thumbnail_immich(self, asset_id):
        """Thumbnail of an Immich asset, by its id (the same on every homeboard).

        Only pictures on some homeboard's screen are fetched, so this can't be used to browse Immich. One fetched
        before is still served after the board moves on, so a page that asked just as it did gets it.
        """
        asset_id = as_asset_id(asset_id)
        if asset_id is None:
            return abort(404, description="Not an Immich asset id")
        on_screen = {as_asset_id((hb['displayed_photo'] or {}).get('id')) for hb in self._core.list_homeboards()}
        try:
            body, ctype = self._thumbs.get(asset_id, may_fetch=asset_id in on_screen)
        except LookupError as e:
            return abort(404, description=str(e))
        except RuntimeError as e:
            log.warning("No thumbnail of %s: %s", asset_id, e)
            return abort(502, description=str(e))
        # An asset never changes picture
        return Response(body, mimetype=ctype, headers={'Cache-Control': 'private, max-age=86400, immutable'})

    def _www_wakeword_ls(self):
        """The wake word recordings kept, newest first.

        Each has `file` (for /wakeword/file/<file>), `received` (unix time we got it) and, from the metadata saved
        next to it, `hb_id`, `id`, `ts`, `duration_ms`, `sample_rate`, `end` and `transcription` (`text`,
        `confidence` and `ts`, once ZmwSpeechToText answered); those are null for a recording saved without
        metadata, whose `received` is the file's mtime.
        """
        try:
            files = _wakeword_recordings(self._wakeword_dir)
        except FileNotFoundError:
            # Nothing was recorded yet
            return {"recordings": []}
        except OSError:
            log.warning("Can't list %s", self._wakeword_dir, exc_info=True)
            return abort(500, description="Can't list the wake word recordings")
        out = []
        for e in files:
            try:
                with open(_wakeword_meta_path(e.path), encoding='utf-8') as fp:
                    meta = json.load(fp)
            except (OSError, ValueError):
                meta = None
            if not isinstance(meta, dict):
                meta = {}
            out.append({
                "file": e.name,
                "received": meta.get('received') or e.stat().st_mtime,
                "size": e.stat().st_size,
                **{k: meta.get(k) for k in ('hb_id', 'id', 'ts', 'duration_ms', 'sample_rate', 'end',
                                            'transcription')},
            })
        return {"recordings": out}

    def _www_wakeword_file(self, name):
        if not _WAKEWORD_FILE_RE.match(name):
            return abort(404)
        # send_from_directory also refuses anything outside the dir
        return send_from_directory(self._wakeword_dir, name, mimetype='audio/wav', as_attachment=True)

    def _www_next(self, hb_id):
        return {"ok": self._core.next(hb_id)}

    def _www_prev(self, hb_id):
        return {"ok": self._core.prev(hb_id)}

    def _www_force_on(self, hb_id):
        return {"ok": self._core.force_on(hb_id)}

    def _www_force_off(self, hb_id):
        return {"ok": self._core.force_off(hb_id)}

    def _www_set_transition_time_secs(self, hb_id, secs):
        if secs < 1:
            return abort(400, description="Transition time must be at least 1 second")
        return {"ok": self._core.set_transition_time_secs(hb_id, secs)}

    def _www_announce_all(self):
        """Show one message on every homeboard.

        This uses the announce command rather than the composed SVG overlay
        (_set_announce): every device speaks it, including ones that have no
        SVG renderer, and they all show the same text at the same time. An
        empty msg clears whatever is on screen.
        """
        try:
            req = request.get_json()
        except Exception as e:
            return abort(400, description=f"Invalid JSON: {e}")
        if not isinstance(req, dict):
            return abort(400, description="Expected a JSON object")

        msg = (req.get('msg') or '').strip()
        try:
            timeout_secs = int(req.get('timeout_secs', 60))
        except (TypeError, ValueError):
            return abort(400, description="timeout_secs must be a number")
        if timeout_secs < 0:
            return abort(400, description="timeout_secs cannot be negative")

        sent_to = []
        failed = []
        for hb in self._active_homeboards():
            if self._core.announce(hb['id'], timeout_secs, msg):
                sent_to.append(hb['id'])
            else:
                failed.append(hb['id'])
        if failed:
            log.warning("Announce failed for %s", failed)
        return {"ok": not failed, "sent_to": sent_to, "failed": failed}

    def _www_set_album_filter_all(self):
        """Set the album filter on every homeboard.

        One filter for all of them; an empty request clears it, which is the
        only way back to showing every album.
        """
        try:
            req = request.get_json()
        except Exception as e:
            return abort(400, description=f"Invalid JSON: {e}")
        if not isinstance(req, dict):
            return abort(400, description="Expected a JSON object")

        filt, err = self._parse_album_filter(req)
        if err is not None:
            return abort(400, description=err)

        sent_to, failed = self._push_album_filter(filt)
        return {"ok": not failed, "album_filter": filt,
                "sent_to": sent_to, "failed": failed}

    def stop(self):
        try:
            self._core.stop()
        finally:
            super().stop()

    def get_mqtt_description(self):
        return {
            "description": "Homeboard service integration",
            "meta": self.get_service_meta(),
            # MQTT data flow; feeds the map in the top-level README (scripts/build_mqtt_map.py).
            # Reads: mirrors live speaker announcements onto the overlay, and
            # tells them when the doorbell rings. Audio announcements come in as
            # announce_audio commands from ZmwSpeakerAnnounce, for the homeboards
            # it targets. Wake word recordings are sent to ZmwSpeechToText, and
            # its transcriptions of them kept.
            # Own state is published too (consumed by ZmwSensormon).
            "reads_mqtt_topic": ["zmw_speaker_announce", "zmw_doorman", "zmw_speech_to_text"],
            "writes_mqtt_topic": [],
            "commands": {
                "next": {
                    "description": "Move slideshow to next picture",
                    "params": {"homeboard_id": "Name of the target homeboard"}
                },
                "prev": {
                    "description": "Move slideshow to previous picture",
                    "params": {"homeboard_id": "Name of the target homeboard"}
                },
                "force_on": {
                    "description": "Force slideshow on",
                    "params": {"homeboard_id": "Name of the target homeboard"}
                },
                "force_off": {
                    "description": "Force slideshow off",
                    "params": {"homeboard_id": "Name of the target homeboard"}
                },
                "set_transition_time_secs": {
                    "description": "Set slideshow transition time in seconds",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "secs": "Transition time in seconds (non-negative integer)",
                    }
                },
                "set_embed_qr": {
                    "description": "Enable or disable embedded QR code on photos",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "enabled": "true/false",
                    }
                },
                "set_target_size": {
                    "description": "Set target photo size in pixels",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "width": "Width in pixels (positive integer)",
                        "height": "Height in pixels (positive integer)",
                    }
                },
                "announce": {
                    "description": "Show an announcement text in the Homeboard overlay (empty msg clears)",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "timeout_secs": "How long to display, in seconds",
                        "msg": "Text to display; empty clears the current announce",
                    }
                },
                "announce_audio": {
                    "description": "Play an audio file on a homeboard, showing msg while it plays. Only for "
                                   "homeboards that can play audio (see ls_audio_targets); dropped for others",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "uri": "URL of the audio to play",
                        "volume?": "Volume 0-100 (default: the device's, 40% on a Portal)",
                        "msg?": "Text being spoken, when the audio comes from a TTS request",
                    }
                },
                "ls_audio_targets": {
                    "description": "List the homeboards that can play audio. Response on ls_audio_targets_reply",
                    "params": {}
                },
                "doorbell_ring": {
                    "description": "Tell a homeboard the doorbell rang (sent to all of them on every ring)",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "rtsp_urls?": "Stream name (main, sub) -> RTSP URL of the door camera",
                    }
                },
                "set_svg_overlay": {
                    "description": "Show an svg overlay in the Homeboards",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "timeout_secs": "How long it should be displayed (0 means forever)",
                        "svg_file_path": "Path to the SVG file in the local filesystem",
                    }
                },
                "set_album_filter": {
                    "description": "Pick which albums every homeboard may show pictures from; "
                                   "an empty request clears the filter and brings back all albums",
                    "params": {
                        "name": "Comma-separated glob patterns (*, ?) matched against the whole "
                                "album name, case-insensitive; empty means every album",
                        "exclude": "Same syntax as name, for albums to drop; wins over name",
                        "from_year": "Only albums holding pictures from this year onwards (0 = no bound)",
                        "to_year": "Only albums holding pictures up to this year (0 = no bound)",
                    }
                },
                "update_weather": {
                    "description": "Recompute and push the overlay for all homeboards",
                },
            },
            "announcements": {
                "audio_targets": {
                    "description": "The homeboards that can play audio (announce_audio), sent whenever that "
                                   "changes. A homeboard that goes offline is only dropped once it's been offline "
                                   "for a while, the next time the list is needed",
                    "payload": ["homeboard_id", "..."]
                },
                "ls_audio_targets_reply": {
                    "description": "Response to ls_audio_targets",
                    "payload": ["homeboard_id", "..."]
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return
        # Self-echo of the homeboard state we republish, on '<hb_id>/<part>';
        # commands are never nested
        if '/' in subtopic:
            return
        # Self-echo of our own announcement
        if subtopic == 'audio_targets':
            return
        if not isinstance(payload, dict):
            log.warning("Ignoring '%s' with non-dict payload: %s", subtopic, payload)
            return

        hb_id = payload.get('homeboard_id')

        if subtopic == "list":
            self.publish_own_svc_message(f'list_reply', self._core.list_homeboards())
            ok = True
        elif subtopic == "ls_audio_targets":
            self.publish_own_svc_message('ls_audio_targets_reply', self._audio_targets())
            ok = True
        elif subtopic == "next":
            ok = self._core.next(hb_id)
        elif subtopic == "prev":
            ok = self._core.prev(hb_id)
        elif subtopic == "force_on":
            ok = self._core.force_on(hb_id)
        elif subtopic == "force_off":
            ok = self._core.force_off(hb_id)
        elif subtopic == "set_transition_time_secs":
            ok = self._core.set_transition_time_secs(hb_id, payload.get('secs', 30))
        elif subtopic == "set_embed_qr":
            ok = self._core.set_embed_qr(hb_id, payload.get('enabled', False))
        elif subtopic == "set_target_size":
            ok = self._core.set_target_size(hb_id, payload.get('width', 1920), payload.get('height', 1080))
        elif subtopic == "announce":
            ok = self._set_announce(hb_id,
                                    payload.get('msg', ''),
                                    payload.get('timeout_secs', 60))
        elif subtopic == "announce_audio":
            if hb_id not in self._audio_targets():
                log.warning("Homeboard '%s' can't play audio (or has been offline for a while), dropping "
                            "announce_audio", hb_id)
                ok = False
            else:
                ok = self._core.announce_audio(hb_id, payload.get('uri'),
                                               payload.get('volume'), payload.get('msg'))
        elif subtopic == "doorbell_ring":
            ok = self._core.doorbell_ring(hb_id, payload.get('rtsp_urls') or {})
        elif subtopic == "set_svg_overlay":
            svg_path = payload.get('svg_file_path')
            if not svg_path:
                # Requested to clear overlay
                ok = self._core.set_svg_overlay(hb_id, timeout_secs=0, svg='')
            else:
                try:
                    with open(svg_path, 'r', encoding='utf-8') as f:
                        svg = f.read()
                except OSError as e:
                    log.warning("Cannot read SVG file '%s': %s", svg_path, e)
                    ok = False
                else:
                    ok = self._core.set_svg_overlay(hb_id, payload.get('timeout_secs', 15), svg)
        elif subtopic == "set_album_filter":
            # Global, like update_weather: one filter goes to every homeboard
            filt, err = self._parse_album_filter(payload)
            if err is not None:
                log.warning("Dropping bad album filter %s: %s", payload, err)
                ok = False
            else:
                _sent_to, failed = self._push_album_filter(filt)
                ok = not failed
        elif subtopic == "update_weather":
            self._recompute_all_overlays(scheduled=False)
            ok = True
        else:
            return

        if not ok:
            log.warning("Failed to execute '%s' for payload: %s", subtopic, payload)


service_runner(ZmwHomeboard)
