"""MQTT to Telegram bridge service."""
import json
import pathlib
import os
import subprocess
import time
import threading
from collections import deque

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner

from pytelegrambot import TelegramLongpollBot
import requests.exceptions

log = build_logger("ZmwTelegram")

_MIME_EXT_MAP = {
    'audio/ogg': '.ogg',
    'audio/mpeg': '.mp3',
    'audio/mp4': '.m4a',
    'audio/x-wav': '.wav',
    'audio/wav': '.wav',
    'audio/flac': '.flac',
    'audio/aac': '.aac',
}


def _voice_dest_path(download_dir, voice_msg):
    """ Build the local destination path for a voice/audio message """
    from_id = voice_msg['from']['id']
    if voice_msg['type'] == 'voice':
        ext = '.ogg'
    else:
        ext = _MIME_EXT_MAP.get(voice_msg['mime_type'], '.bin')
    ts = int(time.time())
    return os.path.join(download_dir, f'voice_{from_id}_{ts}{ext}')


_MAX_VOICE_DURATION_SECS = 60
_MAX_WAV_SIZE_BYTES = 5 * 1024 * 1024
_MAX_VOICE_FILES = 30


def _transcode_to_wav(src_path):
    """ Transcode an audio file to WAV (PCM 16-bit, 16kHz mono) for STT compatibility.
    Returns the wav path on success, or None on failure or if the result is too large. """
    wav_path = os.path.splitext(src_path)[0] + '.wav'
    try:
        subprocess.run(
            ['ffmpeg', '-i', src_path, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', '-y', wav_path],
            check=True, capture_output=True, timeout=30)
    except FileNotFoundError:
        log.warning("ffmpeg not found, can't transcode to wav")
        return None
    except subprocess.TimeoutExpired:
        log.error("ffmpeg transcode timed out for %s", src_path)
        return None
    except subprocess.CalledProcessError as ex:
        log.error("ffmpeg transcode failed for %s: %s", src_path, ex.stderr, exc_info=True)
        return None

    wav_size = os.path.getsize(wav_path)
    if wav_size > _MAX_WAV_SIZE_BYTES:
        log.warning("Transcoded WAV too large (%d bytes), removing %s", wav_size, wav_path)
        os.remove(wav_path)
        return None

    return wav_path


def _cleanup_old_voice_files(download_dir):
    """ Remove oldest files in download_dir, keeping at most _MAX_VOICE_FILES """
    try:
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir)
                 if os.path.isfile(os.path.join(download_dir, f))]
    except FileNotFoundError:
        return
    if len(files) <= _MAX_VOICE_FILES:
        return
    files.sort(key=os.path.getmtime)
    for f in files[:len(files) - _MAX_VOICE_FILES]:
        try:
            os.remove(f)
            log.debug("Cleaned up old voice file %s", f)
        except OSError:
            log.warning("Failed to remove old voice file %s", f, exc_info=True)

class TelBot(TelegramLongpollBot):
    """Telegram bot wrapper that handles messages and commands."""

    _CMD_BATCH_DELAY_SECS = 5

    def __init__(self, cfg, scheduler, on_voice_callback=None):
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
        self._on_voice_callback = on_voice_callback
        self._voice_download_path = cfg['voice_download_path']
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

    def on_bot_received_voice_message(self, voice_msg):
        log.info("Telegram bot received voice message: type=%s, file_id=%s",
                 voice_msg.get('type'), voice_msg.get('file_id'))

        duration = voice_msg.get('duration')
        if duration is not None and duration > _MAX_VOICE_DURATION_SECS:
            log.warning("Voice message too long (%ds > %ds), skipping",
                        duration, _MAX_VOICE_DURATION_SECS)
            return

        dest_path = _voice_dest_path(self._voice_download_path, voice_msg)

        try:
            self.download_file(voice_msg['file_id'], dest_path)
        except Exception:
            log.error("Failed to download Telegram voice file %s", voice_msg['file_id'], exc_info=True)
            return

        wav_path = _transcode_to_wav(dest_path)
        _cleanup_old_voice_files(self._voice_download_path)

        from_id = voice_msg['from']['id']
        from_name = voice_msg['from'].get('first_name', str(from_id))
        log.info("Voice message downloaded: %s (wav: %s, from %s)", dest_path, wav_path, from_name)

        if self._on_voice_callback:
            self._on_voice_callback({
                'path': dest_path,
                'wav_path': wav_path,
                'from_id': from_id,
                'from_name': from_name,
                'chat_id': voice_msg['chat']['id'],
                'duration': duration,
                'original_mime_type': voice_msg['mime_type'],
            })

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
        self._msg = TelBot(cfg, sched, on_voice_callback=self._on_voice_received)
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

    def get_mqtt_description(self):
        return {
            "description": "MQTT-to-Telegram bridge for bidirectional messaging. Runs a Telegram bot that relays commands and voice messages over MQTT, and allows other services to send text or photos through Telegram. Supports rate limiting and voice message transcoding.",
            "meta": self.get_service_meta(),
            "commands": {
                "register_command": {
                    "description": "Register a Telegram bot command that will be relayed over MQTT when invoked",
                    "params": {"cmd": "Command name (without /)", "descr": "Help text for the command"}
                },
                "send_photo": {
                    "description": "Send a photo to a Telegram chat",
                    "params": {"path": "Local file path to the image", "msg": "(optional) Caption", "topic": "(optional) Route to a specific chat via topic_map_chat"}
                },
                "send_text": {
                    "description": "Send a text message to a Telegram chat",
                    "params": {"msg": "Message text", "topic": "(optional) Route to a specific chat via topic_map_chat"}
                },
                "get_history": {
                    "description": "Request message history. Response published on get_history_reply",
                    "params": {}
                },
            },
            "announcements": {
                "on_command/<cmd>": {
                    "description": "Published when a registered Telegram command is received",
                    "payload": {"cmd": "The command name", "cmd_args": "List of arguments", "from": "Sender info", "chat": "Chat info"}
                },
                "on_voice": {
                    "description": "Published when a voice/audio message is received (max 60s)",
                    "payload": {"path": "Original audio file path", "wav_path": "Transcoded WAV path (null if failed)", "from_id": "Sender ID", "from_name": "Sender name", "chat_id": "Chat ID", "duration": "Duration in seconds", "original_mime_type": "MIME type of original audio"}
                },
                "get_history_reply": {
                    "description": "Response to get_history. List of message objects",
                    "payload": [{"timestamp": "ISO timestamp", "direction": "sent|received", "message": "Message content"}]
                },
            }
        }

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
        if subtopic.startswith('on_voice'):
            return
        if subtopic.endswith('_reply'):
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
            case "get_history":
                self.publish_own_svc_message("get_history_reply",
                    list(self._msg.get_history()))
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                log.error("Ignoring unknown message '%s'", subtopic)

    def _on_voice_received(self, voice_data):
        self.publish_own_svc_message("on_voice", voice_data)

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
