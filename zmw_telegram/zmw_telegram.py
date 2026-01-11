"""MQTT to Telegram bridge service."""
import json
import pathlib
import os
import time
import threading
from collections import deque

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner

from pytelegrambot import TelegramLongpollBot
import requests.exceptions

log = build_logger("ZmwTelegram")

class TelBot(TelegramLongpollBot):
    """Telegram bot wrapper that handles messages and commands."""

    _CMD_BATCH_DELAY_SECS = 5

    def __init__(self, cfg, scheduler):
        cmds = [
            ('ping', 'Usage: /ping', self._ping),
        ]
        super().__init__(
            cfg['tok'],
            accepted_chat_ids=cfg['accepted_chat_ids'],
            short_poll_interval_secs=cfg['short_poll_interval_secs'],
            long_poll_interval_secs=cfg['long_poll_interval_secs'],
            cmds=cmds,
            bot_name=cfg['bot_name'],
            bot_descr=cfg['bot_name'],
            message_history_len=cfg['msg_history_len'],
            terminate_on_unauthorized_access=True,
            try_parse_msg_as_cmd=True,
            scheduler=scheduler)
        self._pending_cmds = []
        self._cmd_timer = None
        self._cmd_lock = threading.Lock()
        self._stfu_until = 0
        self.add_commands([('stfu', 'Suppress messages for N minutes (default 10)', self._stfu)])

    def _stfu(self, _bot, msg):
        """Suppress outgoing messages for a specified number of minutes."""
        minutes = 10
        if msg['cmd_args']:
            try:
                minutes = int(msg['cmd_args'][0])
            except ValueError:
                self.send_message(msg['from']['id'], f"Invalid argument: {msg['cmd_args'][0]}")
                return
        self._stfu_until = time.time() + minutes * 60
        try:
            super().send_message(msg['from']['id'], f"Messages suppressed for {minutes} minutes")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            log.warning("Can't connect to Telegram server: %s", e)

    def _is_stfu_active(self):
        return time.time() < self._stfu_until

    def send_message(self, chat_id, text, disable_notifications=False):
        if self._is_stfu_active():
            log.info("Message skipped, stfu active: %s", text)
            return
        try:
            super().send_message(chat_id, text, disable_notifications)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            log.warning("Can't connect to Telegram server: %s", e)

    def send_photo(self, chat_id, fpath, caption=None, disable_notifications=False):
        if self._is_stfu_active():
            log.info("Message skipped, stfu active: %s (caption: %s)", fpath, caption)
            return
        try:
            super().send_photo(chat_id, fpath, caption, disable_notifications)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            log.warning("Can't connect to Telegram server: %s", e)

    def add_commands(self, cmds):
        """Batch commands and register them after a delay.

        Commands are collected and set_commands is called after 5 seconds.
        If new commands arrive during the delay, the timer is reset.
        """
        with self._cmd_lock:
            if self._cmd_timer is not None:
                self._cmd_timer.cancel()
            self._pending_cmds.extend(cmds)
            self._cmd_timer = threading.Timer(self._CMD_BATCH_DELAY_SECS, self._flush_pending_commands)
            self._cmd_timer.start()

    def _flush_pending_commands(self):
        """Called after timeout to register all pending commands."""
        with self._cmd_lock:
            if not self._pending_cmds:
                return
            cmds_to_register = self._pending_cmds
            self._pending_cmds = []
            self._cmd_timer = None
        cmd_names = [cmd[0] for cmd in cmds_to_register]
        log.info("Flushing %d batched commands to Telegram: %s", len(cmds_to_register), cmd_names)
        try:
            super().add_commands(cmds_to_register)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            log.warning("Can't connect to Telegram server: %s", e)

    def _ping(self, _bot, msg):
        log.info('Received user ping, sending pong')
        if len(msg['cmd_args']) == 0:
            self.send_message(msg['from']['id'], "PONG")
        else:
            t = ' '.join(msg['cmd_args'])
            self.send_message(msg['from']['id'], f"Echo: {t}")

    def on_bot_received_non_cmd_message(self, msg):
        """ Called when a message not in the list of commands is received. This is benign, it just means someone
        set a message in Telegram, but it's a known recipient """
        log.warning("Telegram bot received unknown message: %s", msg)

class ZmwTelegram(ZmwMqttService):
    """MQTT to Telegram bridge service for bidirectional messaging."""

    _RATE_LIMIT_MAX_MSGS = 3
    _RATE_LIMIT_WINDOW_SECS = 60

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_telegram", scheduler=sched)
        self._bcast_chat_id = cfg['bcast_chat_id']
        self._topic_map_chat = cfg['topic_map_chat']
        self._msg = TelBot(cfg, sched)
        self._msg_times = deque(maxlen=self._RATE_LIMIT_MAX_MSGS)

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/messages', lambda: json.dumps(list(self._msg.get_history()), default=str))

    def get_service_alerts(self):
        alerts = []
        if len(self._msg_times) == self._RATE_LIMIT_MAX_MSGS:
            oldest = self._msg_times[0]
            if time.time() - oldest < self._RATE_LIMIT_WINDOW_SECS:
                alerts.append("Currently rate limiting")
        return alerts

    def _get_chat_id_for_payload(self, payload):
        """Get the chat ID based on payload topic, or default to broadcast chat."""
        topic = payload.get('topic')
        if topic and topic in self._topic_map_chat:
            return self._topic_map_chat[topic]
        return self._bcast_chat_id

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
        if subtopic.startswith('on_command/'):
            # We're relaying a Telegram command over mqtt, ignore self-echo
            return

        match subtopic:
            case "register_command":
                if 'cmd' not in payload or 'descr' not in payload:
                    log.error("Received request to add command, but missing 'cmd' or 'descr': '%s'", payload)
                    return
                log.info("Registered new user command '%s' for mqtt-relaying: '%s'", payload['cmd'], payload['descr'])
                self._msg.add_commands([(payload['cmd'], payload['descr'], self._relay_cmd)])
            case "send_photo":
                if not 'path' in payload:
                    log.error("Received request to send image but payload has no path: '%s'", payload)
                    return
                if not os.path.isfile(payload['path']):
                    log.error("Received request to send image but path is not a file: '%s'", payload)
                    return
                chat_id = self._get_chat_id_for_payload(payload)
                log.info("Sending photo to chat %s, path %s", chat_id, payload['path'])
                self._rate_limited_send(
                    lambda: self._msg.send_photo(chat_id, payload['path'], payload.get('msg', None)))
            case "send_text":
                if not 'msg' in payload:
                    log.error("Received request to send message but payload has no text: '%s'", payload)
                    return
                chat_id = self._get_chat_id_for_payload(payload)
                log.info("Sending text to chat %s, message %s", chat_id, payload['msg'])
                self._rate_limited_send(lambda: self._msg.send_message(chat_id, payload['msg']))
            case _:
                log.error("Ignoring unknown message '%s'", subtopic)

    def _relay_cmd(self, _bot, msg):
        """ Relay an mqtt-registered callback from Telegram back to mqtt. The Telegram client already
        validates this command is known, so we can just relay the command itself. """
        if 'cmd' not in msg:
            log.warning("Received user message but can't find associated cmd. Ignoring. Full message:\n\t%s", msg)
            return

        log.info("Received Telegram command '%s', relaying over mqtt", msg['cmd'])
        # Commands may have a / as a prefix, strip it to ensure we only send a single slash
        if msg['cmd'][0] == '/':
            cmd = msg['cmd'][1:]
        else:
            cmd = msg['cmd']
        self.publish_own_svc_message(f"on_command/{cmd}", msg)

service_runner(ZmwTelegram)
