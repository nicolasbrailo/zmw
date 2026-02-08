""" MQTT to Whatsapp bridge service. """

import json
import os
import pathlib
import time
from datetime import datetime
from collections import deque

from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from whatsapp import WhatsApp

log = build_logger("ZmwWhatsapp")

class ZmwWhatsapp(ZmwMqttService):
    """ Expose Whatsapp methods over MQTT """

    _RATE_LIMIT_MAX_MSGS = 3
    _RATE_LIMIT_WINDOW_SECS = 60

    def __init__(self, cfg, www, _sched):
        super().__init__(cfg, "zmw_whatsapp", scheduler=_sched)
        self._wa = WhatsApp(cfg, test_mode=False)
        self._message_history = deque(maxlen=cfg['msg_history_len'])
        self._msg_times = deque(maxlen=self._RATE_LIMIT_MAX_MSGS)

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/messages', lambda: json.dumps(list(self._message_history), default=str))

    def get_service_alerts(self):
        alerts = []
        if len(self._msg_times) == self._RATE_LIMIT_MAX_MSGS:
            oldest = self._msg_times[0]
            if time.time() - oldest < self._RATE_LIMIT_WINDOW_SECS:
                alerts.append("Currently rate limiting")
        return alerts

    def get_mqtt_description(self):
        return {
            "description": "MQTT-to-WhatsApp bridge for sending photos and messages via the WhatsApp Business Cloud API. Supports sending photos to configured phone numbers with rate limiting.",
            "meta": self.get_service_meta(),
            "commands": {
                "send_photo": {
                    "description": "Send a photo to all WhatsApp notify targets via a template message",
                    "params": {"path": "Local file path to the image", "msg": "(optional) Caption text"}
                },
                "send_text": {
                    "description": "Send a text message to all WhatsApp notify targets (not yet implemented)",
                    "params": {"msg": "Message text"}
                },
                "get_history": {
                    "description": "Request message history. Response published on get_history_reply",
                    "params": {}
                },
            },
            "announcements": {
                "get_history_reply": {
                    "description": "Response to get_history. List of message event objects",
                    "payload": [{"timestamp": "ISO timestamp", "direction": "sent", "type": "photo|text", "...": "Additional details depending on type"}]
                },
            }
        }

    def _track_message(self, direction, msg_type, **details):
        """Track message events for history"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'direction': direction,  # 'sent'
            'type': msg_type,
        }
        event.update(details)
        self._message_history.append(event)

    def _rate_limited_send(self, send_fn):
        """Rate-limit outgoing messages. Allows max 3 messages per minute.
        Continued attempts reset the cooldown window."""
        now = time.time()
        oldest = self._msg_times[0] if len(self._msg_times) == self._RATE_LIMIT_MAX_MSGS else None
        # Append message first, so that if spamming never stops we don't enable messaging again
        # Only after a minute of no-messages we'll allow now ones to go through
        self._msg_times.append(now)
        if oldest is not None and now - oldest < self._RATE_LIMIT_WINDOW_SECS:
            log.error("Rate limit exceeded: %d messages in the last %d seconds, dropping message",
                      self._RATE_LIMIT_MAX_MSGS, self._RATE_LIMIT_WINDOW_SECS)
            return
        send_fn()

    def on_service_received_message(self, subtopic, payload):
        """ MQTT callback """
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "send_photo":
                if 'path' not in payload:
                    log.error("Received request to send image but payload has no path: '%s'", payload)
                    return
                if not os.path.isfile(payload['path']):
                    log.error("Received request to send image but path is not a file: '%s'", payload['path'])
                    return
                def do_send_photo():
                    self._wa.send_photo(payload['path'], payload['msg'])
                    self._track_message('sent', 'photo', path=payload['path'], caption=payload.get('msg'))
                self._rate_limited_send(do_send_photo)
            case "send_text":
                if 'msg' not in payload:
                    log.error("Received request to send text but payload has no msg: '%s'", payload)
                    return
                def do_send_text():
                    log.warning("User requested Whatsapp text, but this isn't implemented: '%s'", payload)
                    self._track_message('sent', 'text', text=payload['msg'], status='not_implemented')
                self._rate_limited_send(do_send_text)
            case "get_history":
                self.publish_own_svc_message("get_history_reply",
                    list(self._message_history))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.error("Ignoring unknown message '%s'", subtopic)

service_runner(ZmwWhatsapp)
