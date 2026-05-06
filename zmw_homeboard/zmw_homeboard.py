import os
import pathlib
from datetime import datetime, timedelta

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from homeboard_remote_control import RemoteControlCore
from weather_overlay import WeatherOverlay

log = build_logger("ZmwHomeboard")


class ZmwHomeboard(ZmwMqttService):
    """
    Bridge between the homeboard MQTT broker and the ZMW bus.

    Uses homeboard_remote_control.RemoteControlCore to talk to homeboards.
    Republishes selected homeboard state onto the ZMW bus so other ZMW
    services can consume it. Accepts ZMW-bus commands and forwards them to
    the target homeboard. Serves a read-only status page showing the last
    state each homeboard announced; the user-facing remote control UI lives
    in wwwslide.
    """

    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_homeboard", scheduler=_sched)

        self._sched = _sched
        self._weather = WeatherOverlay(
            "weather_icons",
            lat=float(cfg['weather']['lat']),
            lon=float(cfg['weather']['lon']),
            tz=cfg['weather'].get('tz', 'auto'),
        )

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

        _sched.add_job(self._weather_update,
                       trigger='cron', hour='7-22', minute=0)
        _sched.add_job(self._scheduled_weather_clear,
                       trigger='cron', hour=23, minute=0)

    def _weather_update(self, scheduled=True):
        targets = self._core.list_homeboards()
        log.info("Starting weather update for %s homeboards", len(targets))
        for hb in targets:
            try:
                # TODO: If 23-7 (make this config) then clear overlay
                svg = self._weather.generate_svg(hb.get('host_info', {}))
            except Exception:
                log.exception(f"Weather update: generate_svg raised for Homeboard {hb['id']}")
                continue
            if svg is None and scheduled:
                log.info("Scheduled weather update failed: no SVG (network error?), retrying in 60s")
                self._sched.add_job(self._weather_update,
                                    trigger='date',
                                    run_date=datetime.now() + timedelta(seconds=60))
                return
            self._core.set_svg_overlay(hb['id'], timeout_secs=60*60, svg=svg)
            log.info("Set SVG overlay for %s", hb['id'])

    def _scheduled_weather_clear(self):
        targets = self._core.list_homeboards()
        log.info("Starting scheduled weather overlay cleanup for %s homeboards", len(targets))
        for hb in targets:
            self._broadcast_svg_overlay('', action="clear")
            self._core.set_svg_overlay(hb_id, timeout_secs=0, svg=svg)
        return True

    def _on_hb_host_info(self, hb_id, _data):
        log.info("Config for '%s' was updating, forcing overlay recompute", hb_id)
        # Force recompute for every HB. Slightly wasteful, but unless we have 12s of HBs it's OK
        # Weather report is the slow part, and it should be memoized
        self._weather_update(scheduled=False)

    def _broadcast_svg_overlay(self, svg, action):
        targets = [hb["id"] for hb in self._core.list_homeboards()]
        if not targets:
            log.info("SVG overlay bcast %s: no homeboards discovered yet", action)
            return True
        for hb_id in targets:
            try:
                log.info("%s SVG overlay for %s", action, hb_id)
            except Exception:
                log.exception("Scheduled weather %s raised for %s", action, hb_id)
                continue
            if not ok:
                log.warning("Scheduled weather %s failed for %s", action, hb_id)
        return True

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
                    "description": "Show an announcement text in the Homeboards",
                    "params": {
                        "homeboard_id": "Name of the target homeboard",
                        "timeout_secs": "How long it should be displayed (0 means forever)",
                        "msg": "Text to display",
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
                    "description": "Push a new weather update to the Homeboards as an SVG",
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
            ok = self._core.announce(hb_id, payload.get('timeout_secs', 15), payload.get('msg'))
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
            self._weather_update(scheduled=False)
            ok = True
        else:
            return

        if not ok:
            log.warning("Failed to execute '%s' for payload: %s", subtopic, payload)


service_runner(ZmwHomeboard)
