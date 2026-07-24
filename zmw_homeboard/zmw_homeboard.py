import os
import pathlib
import time
from datetime import datetime, timedelta

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from homeboard_remote_control import RemoteControlCore

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

_QR_URL_TEMPLATE = "{rc_url}/remote_control?hb_id={hb_id}"

# How long a mirrored speaker announcement stays on the overlay, in seconds.
_SPEAKER_ANNOUNCE_OVERLAY_SECS = 60


class ZmwHomeboard(ZmwMqttService):
    """
    Bridge between the homeboard MQTT broker and the ZMW bus.

    Uses homeboard_remote_control.RemoteControlCore to talk to homeboards.
    Republishes selected homeboard state onto the ZMW bus so other ZMW
    services can consume it. Accepts ZMW-bus commands and forwards them to
    the target homeboard. Composes per-homeboard SVG overlays (weather +
    QR + announcements) and pushes them via set_svg_overlay.
    """

    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_homeboard", scheduler=_sched,
                         svc_deps=["ZmwSpeakerAnnounce"])

        self._sched = _sched
        self._weather = WeatherOverlay(
            "weather_icons",
            lat=float(cfg['weather']['lat']),
            lon=float(cfg['weather']['lon']),
            tz=cfg['weather'].get('tz', 'auto'),
        )
        self._qr = QrOverlay()
        self._announce = AnnounceOverlay()

        # hb_id -> (text, expires_at_ts). Only kept while the announce is live.
        self._announce_state = {}

        self._core = RemoteControlCore(
            cfg['homeboard']['mqtt_ip'],
            int(cfg['homeboard']['mqtt_port']),
            on_occupancy=lambda prefix, data:
                self.publish_own_svc_message(f'{prefix}/occupancy', data),
            on_slideshow_active=lambda prefix, active:
                self.publish_own_svc_message(f'{prefix}/slideshow_active', active),
            on_host_info=self._on_hb_host_info,
        )
        self._core.start()

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.register_www_dir(www_path)
        www.serve_url('/get_homeboards_state', self._get_homeboards_state)

        _sched.add_job(self._recompute_all_overlays,
                       trigger='cron', hour='7-22', minute=0)
        _sched.add_job(self._clear_all_overlays,
                       trigger='cron', hour=23, minute=0)

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
            qr_frag = self._qr.build_fragment(_QR_URL_TEMPLATE.format(rc_url=self._core.get_remote_control_url(), hb_id=hb['id']))
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
        for hb in self._core.list_homeboards():
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

        targets = self._core.list_homeboards()
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
        targets = self._core.list_homeboards()
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

    def _on_hb_host_info(self, hb_id, _data):
        log.info("Config for '%s' changed, recomputing overlay", hb_id)
        # Recompute everyone: weather is the slow part and is memoized, so
        # this is cheap unless we have many homeboards.
        self._recompute_all_overlays(scheduled=False)

    def on_dep_published_message(self, svc_name, subtopic, payload):
        # Mirror live speaker announcements onto every homeboard overlay: when
        # ZmwSpeakerAnnounce speaks something, show the same text as if 'announce'
        # had been called over MQTT for each homeboard.
        if svc_name == "ZmwSpeakerAnnounce" and subtopic == "announcement_in_progress":
            if not isinstance(payload, dict):
                log.warning("ZmwSpeakerAnnounce announcement_in_progress with bad payload: %s", payload)
                return
            text = (payload.get('msg') or '').strip()
            if not text:
                return
            log.info("Mirroring speaker announcement onto homeboards: '%s'", text)
            for hb in self._core.list_homeboards():
                self._set_announce(hb['id'], text, _SPEAKER_ANNOUNCE_OVERLAY_SECS)

    def _get_homeboards_state(self):
        return {"homeboards": self._core.list_homeboards()}

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
            # Reads: mirrors live speaker announcements onto the overlay.
            # Own state is published too (consumed by ZmwSensormon).
            "reads_mqtt_topic": ["zmw_speaker_announce"],
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
                "set_svg_overlay": {
                    "description": "Show an svg overlay in the Homeboards",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "timeout_secs": "How long it should be displayed (0 means forever)",
                        "svg_file_path": "Path to the SVG file in the local filesystem",
                    }
                },
                "update_weather": {
                    "description": "Recompute and push the overlay for all homeboards",
                },
            },
            "announcements": {
            }
        }

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return
        if not isinstance(payload, dict):
            log.warning("Ignoring '%s' with non-dict payload: %s", subtopic, payload)
            return

        hb_id = payload.get('homeboard_id')

        if subtopic == "list":
            self.publish_own_svc_message(f'list_reply', self._core.list_homeboards())
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
        elif subtopic == "update_weather":
            self._recompute_all_overlays(scheduled=False)
            ok = True
        else:
            return

        if not ok:
            log.warning("Failed to execute '%s' for payload: %s", subtopic, payload)


service_runner(ZmwHomeboard)
