import os
import pathlib

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from homeboard_remote_control import RemoteControlCore

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

        self._core = RemoteControlCore(
            cfg['homeboard']['mqtt_ip'],
            int(cfg['homeboard']['mqtt_port']),
            on_occupancy=lambda prefix, data:
                self.publish_own_svc_message(f'{prefix}/occupancy', data),
            on_slideshow_active=lambda prefix, active:
                self.publish_own_svc_message(f'{prefix}/slideshow_active', active),
        )
        self._core.start()

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.register_www_dir(www_path)
        www.serve_url('/get_homeboards_state', self._get_homeboards_state)

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

        if subtopic == "next":
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
        else:
            return

        if not ok:
            log.warning("Failed to execute '%s' for payload: %s", subtopic, payload)


service_runner(ZmwHomeboard)
