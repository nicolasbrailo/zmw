import json
import os
import pathlib
import threading

import paho.mqtt.client as mqtt
from flask import abort, request

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

log = build_logger("ZmwHomeboard")


class ZmwHomeboard(ZmwMqttService):
    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_homeboard", scheduler=_sched)

        hb_ip = cfg['homeboard']['mqtt_ip']
        hb_port = int(cfg['homeboard']['mqtt_port'])
        self._hb_broker = (hb_ip, hb_port)

        self._homeboards_lock = threading.Lock()
        self._homeboards = {}
        self._displayed_photos = {}
        self._slideshow_active = {}
        self._occupancy = {}

        self._hb_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"zmw_homeboard_{os.getpid()}")
        self._hb_client.on_connect = self._on_hb_connect
        self._hb_client.on_message = self._on_hb_message
        log.info("Connecting to homeboard MQTT broker [%s]:%d...", hb_ip, hb_port)
        self._hb_client.connect_async(hb_ip, hb_port, 30)
        self._hb_client.loop_start()

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/list', self._http_list)
        www.serve_url('/displayed_photo', self._http_displayed_photo)
        www.serve_url('/next', self._http_next, methods=['PUT'])
        www.serve_url('/prev', self._http_prev, methods=['PUT'])
        www.serve_url('/force_on', self._http_force_on, methods=['PUT'])
        www.serve_url('/force_off', self._http_force_off, methods=['PUT'])
        www.serve_url('/set_transition_time_secs',
                      self._http_set_transition_time_secs, methods=['PUT'])
        www.serve_url('/set_embed_qr', self._http_set_embed_qr, methods=['PUT'])
        www.serve_url('/set_target_size', self._http_set_target_size, methods=['PUT'])

    def stop(self):
        try:
            self._hb_client.loop_stop()
            self._hb_client.disconnect()
        finally:
            super().stop()

    def _on_hb_connect(self, client, _ud, _flags, ret_code, _props):
        if ret_code == 0:
            log.info("Connected to homeboard MQTT broker %s", self._hb_broker)
        else:
            log.warning("Homeboard MQTT connect to %s returned rc=%s",
                        self._hb_broker, ret_code)
        # Bridges publish "<prefix>state/bridge" as retained "online"/"offline".
        # Subscribing to this wildcard lets us enumerate all registered prefixes.
        client.subscribe('+/state/bridge', qos=0)
        client.subscribe('+/state/displayed_photo', qos=0)
        client.subscribe('+/state/slideshow_active', qos=0)
        client.subscribe('+/state/occupancy', qos=0)

    def _on_hb_message(self, _client, _ud, msg):
        parts = msg.topic.split('/')
        if len(parts) != 3 or parts[1] != 'state':
            return
        prefix = parts[0]
        suffix = parts[2]
        if suffix == 'bridge':
            self._handle_bridge_state(prefix, msg.payload)
        elif suffix == 'displayed_photo':
            self._handle_displayed_photo(prefix, msg.payload)
        elif suffix == 'slideshow_active':
            self._handle_slideshow_active(prefix, msg.payload)
        elif suffix == 'occupancy':
            self._handle_occupancy(prefix, msg.payload)

    def _handle_bridge_state(self, prefix, raw_payload):
        try:
            state = raw_payload.decode('utf-8').strip().strip('"').lower()
        except UnicodeDecodeError:
            log.warning("Non-utf8 bridge state for '%s'", prefix)
            return
        if state not in ('online', 'offline'):
            log.warning("Unexpected bridge state '%s' for '%s'", state, prefix)
            return
        with self._homeboards_lock:
            prev = self._homeboards.get(prefix)
            self._homeboards[prefix] = state
        if prev != state:
            log.info("Homeboard '%s' is %s", prefix, state)

    def _handle_displayed_photo(self, prefix, raw_payload):
        try:
            data = json.loads(raw_payload.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("Non-JSON displayed_photo for '%s'", prefix)
            return
        if not isinstance(data, dict):
            log.warning("displayed_photo for '%s' is not a JSON object", prefix)
            return
        with self._homeboards_lock:
            self._displayed_photos[prefix] = data
        log.info("Homeboard '%s' displaying: %s", prefix, data.get('filename'))

    def _handle_occupancy(self, prefix, raw_payload):
        try:
            data = json.loads(raw_payload.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("Non-JSON occupancy for '%s'", prefix)
            return
        if not isinstance(data, dict):
            log.warning("occupancy for '%s' is not a JSON object", prefix)
            return
        with self._homeboards_lock:
            self._occupancy[prefix] = data

        # Republish to ZMW MQTT bus, so it can be consumed by other services
        self.publish_own_svc_message(f'{prefix}/occupancy', data)

    def _handle_slideshow_active(self, prefix, raw_payload):
        try:
            text = raw_payload.decode('utf-8').strip().strip('"').lower()
        except UnicodeDecodeError:
            log.warning("Non-utf8 slideshow_active for '%s'", prefix)
            return
        if text in ('1', 'true', 'on', 'active', 'yes'):
            active = True
        elif text in ('0', 'false', 'off', 'inactive', 'no'):
            active = False
        else:
            log.warning("Unknown slideshow_active value '%s' for '%s'", text, prefix)
            return
        with self._homeboards_lock:
            prev = self._slideshow_active.get(prefix)
            self._slideshow_active[prefix] = active
        if prev != active:
            log.info("Homeboard '%s' slideshow %s", prefix,
                     "active" if active else "inactive")
        # Republish to ZMW MQTT bus, so it can be consumed by other services
        self.publish_own_svc_message(f'{prefix}/slideshow_active', active)

    def _http_list(self):
        with self._homeboards_lock:
            items = [{
                "id": k,
                "state": v,
                "slideshow_active": self._slideshow_active.get(k),
                "occupancy": self._occupancy.get(k),
            } for k, v in sorted(self._homeboards.items())]
        return {"homeboards": items}

    def _http_displayed_photo(self):
        hb_id = self._validate_homeboard_id(request.args.get('homeboard_id'))
        if hb_id is None:
            return abort(400, description="Missing or invalid homeboard_id")
        with self._homeboards_lock:
            photo = self._displayed_photos.get(hb_id)
        return {"displayed_photo": photo}

    @staticmethod
    def _validate_homeboard_id(hb_id):
        if not isinstance(hb_id, str) or not hb_id:
            return None
        if any(c in hb_id for c in ('/', '#', '+')):
            return None
        return hb_id

    def _send_cmd(self, homeboard_id, service, command, payload="{}"):
        topic = f"{homeboard_id}/cmd/{service}/{command}"
        log.info("Publishing '%s' (%s) to homeboard broker", topic, payload)
        info = self._hb_client.publish(topic, payload, qos=0)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("Failed to publish '%s', rc=%s", topic, info.rc)

    def _read_json_body(self):
        try:
            payload = request.get_json(force=True)
        except Exception:
            return abort(400, description="Invalid JSON body")
        if not isinstance(payload, dict):
            return abort(400, description="Body must be a JSON object")
        return payload

    def _read_hb_id_from_body(self):
        body = self._read_json_body()
        hb_id = self._validate_homeboard_id(body.get('homeboard_id'))
        if hb_id is None:
            return abort(400, description="Missing or invalid homeboard_id")
        return body, hb_id

    @staticmethod
    def _as_positive_int(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, int) and v >= 0:
            return v
        if isinstance(v, str):
            try:
                n = int(v)
                return n if n >= 0 else None
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_bool(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int,)) and v in (0, 1):
            return bool(v)
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ('1', 'true', 'yes', 'on'):
                return True
            if s in ('0', 'false', 'no', 'off'):
                return False
        return None

    # --- HTTP handlers for ambience.next / .prev / .force_on / .force_off ---

    def _http_next(self):
        _, hb_id = self._read_hb_id_from_body()
        self._send_cmd(hb_id, 'ambience', 'next')
        return {}

    def _http_prev(self):
        _, hb_id = self._read_hb_id_from_body()
        self._send_cmd(hb_id, 'ambience', 'prev')
        return {}

    def _http_force_on(self):
        _, hb_id = self._read_hb_id_from_body()
        self._send_cmd(hb_id, 'ambience', 'force_on')
        return {}

    def _http_force_off(self):
        _, hb_id = self._read_hb_id_from_body()
        self._send_cmd(hb_id, 'ambience', 'force_off')
        return {}

    def _http_set_transition_time_secs(self):
        body, hb_id = self._read_hb_id_from_body()
        secs = self._as_positive_int(body.get('secs'))
        if secs is None:
            return abort(400, description="Missing or invalid 'secs' (non-negative integer)")
        self._send_cmd(hb_id, 'ambience', 'set_transition_time_secs', str(secs))
        return {}

    def _http_set_embed_qr(self):
        body, hb_id = self._read_hb_id_from_body()
        enabled = self._as_bool(body.get('enabled'))
        if enabled is None:
            return abort(400, description="Missing or invalid 'enabled' (bool)")
        self._send_cmd(hb_id, 'photo_provider', 'set_embed_qr', '1' if enabled else '0')
        return {}

    def _http_set_target_size(self):
        body, hb_id = self._read_hb_id_from_body()
        width = self._as_positive_int(body.get('width'))
        height = self._as_positive_int(body.get('height'))
        if width is None or width == 0 or height is None or height == 0:
            return abort(400, description="Missing or invalid 'width'/'height' (positive integers)")
        self._send_cmd(hb_id, 'photo_provider', 'set_target_size', f"{width}x{height}")
        return {}

    # --- MQTT command handlers ---

    def _mqtt_cmd(self, payload, service, command, body_payload_fn=None):
        hb_id = self._validate_homeboard_id(
            payload.get('homeboard_id') if isinstance(payload, dict) else None)
        if hb_id is None:
            log.warning("Missing homeboard_id in mqtt '%s' command", command)
            return
        body_payload = "{}"
        if body_payload_fn is not None:
            body_payload = body_payload_fn(payload)
            if body_payload is None:
                log.warning("Invalid payload for mqtt '%s' command: %s", command, payload)
                return
        self._send_cmd(hb_id, service, command, body_payload)

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

        def _transition_payload(p):
            secs = self._as_positive_int(p.get('secs'))
            return None if secs is None else str(secs)

        def _embed_qr_payload(p):
            enabled = self._as_bool(p.get('enabled'))
            return None if enabled is None else ('1' if enabled else '0')

        def _target_size_payload(p):
            w = self._as_positive_int(p.get('width'))
            h = self._as_positive_int(p.get('height'))
            if not w or not h:
                return None
            return f"{w}x{h}"

        match subtopic:
            case "next":
                self._mqtt_cmd(payload, 'ambience', 'next')
            case "prev":
                self._mqtt_cmd(payload, 'ambience', 'prev')
            case "force_on":
                self._mqtt_cmd(payload, 'ambience', 'force_on')
            case "force_off":
                self._mqtt_cmd(payload, 'ambience', 'force_off')
            case "set_transition_time_secs":
                self._mqtt_cmd(payload, 'ambience', 'set_transition_time_secs',
                               _transition_payload)
            case "set_embed_qr":
                self._mqtt_cmd(payload, 'photo_provider', 'set_embed_qr',
                               _embed_qr_payload)
            case "set_target_size":
                self._mqtt_cmd(payload, 'photo_provider', 'set_target_size',
                               _target_size_payload)
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

service_runner(ZmwHomeboard)
