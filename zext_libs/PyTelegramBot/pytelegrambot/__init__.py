""" Trivial Telegram wrapper """

from abc import ABC, abstractmethod
from apscheduler.schedulers.background import BackgroundScheduler
from collections import deque
from datetime import datetime
import base64
import json
import logging
import os
import requests
import time


log = logging.getLogger(__name__)

logging.getLogger('urllib3.connectionpool').setLevel(logging.ERROR)
logging.getLogger('apscheduler.scheduler').setLevel(logging.ERROR)
logging.getLogger('apscheduler.executors.default').setLevel(logging.ERROR)


# If a message received from the user is longer than this, it will be
# discarded for security
_MAX_USER_MESSAGE_LEN = 150
# If a user command can be split into more than N tokens, discard it for
# security
_MAX_USER_CMD_TOKS = 20

def _stringify(*a, **kw):
    """ Used to keep history of messages """
    return ", ".join(
        [*map(str, a)] +
        [f"{k}={v}" for k, v in kw.items()]
    )

def mk_log_sent_msg(*a, **kw):
    """ Helper to keep a log of sent messages """
    return {
        'timestamp': datetime.now().isoformat(),
        'direction': 'sent',
        'message': _stringify(*a, **kw),
    }


class TelegramApiError(RuntimeError):
    """ The Telegram API responded with something we don't know how to parse, or the
    message sent to Telegram caused an error """
    pass


class TelegramRateLimitError(RuntimeError):
    """ Currently being ratelimited by the API """
    pass


class TelegramHttpError(RuntimeError):
    """ Transport error """
    pass


class TelegramUnauthorizedBotAccess(RuntimeError):
    """ Someone sent a message to this bot, and is not in the allow-list """
    pass


def _telegram_req(url, params=None, data=None, files=None, post=False):
    try:
        req_method = requests.post if post else requests.get
        req = req_method(url, params=params, data=data, files=files)
        if req.status_code == 429:
            raise TelegramRateLimitError()

        if req.status_code != 200:
            try:
                sdata = json.dumps(data)
            except BaseException:
                sdata = '<???>'
            raise TelegramHttpError(
                f'Telegram request {url} failed, status {req.status_code} - {req.reason}. Message: {sdata}')

        jreq = req.json()
        if not jreq['ok']:
            raise TelegramApiError(jreq['description'])

        return jreq['result']
    except requests.exceptions.ConnectionError as ex:
        raise
    except requests.exceptions.RequestException as ex:
        raise TelegramHttpError(f'Telegram request {url} failed') from ex


_telegram_get = _telegram_req


def _telegram_post(*a, **kw):
    kw['post'] = True
    return _telegram_req(*a, **kw)


def _validate_telegram_cmds(cmds):
    fmt_cmds = []
    known_commands = {}

    # If cmds is a dict instead of a list, transform to a list by dropping all keys. This is done
    # to make _validate_telegram_cmds idempotent
    if type(cmds) == type({}):
        cmds = [x.values() for x in cmds.values()]

    for cmd in cmds:
        try:
            cmd, descr, cb = cmd
        except ValueError as ex:
            raise ValueError(
                f'TelegramBot {cmd} not valid: format should be tuple of (command, description, callback)') from ex

        # Telegram API requires lowercase commands - normalize and warn if needed
        cmd_lower = cmd.lower()
        if cmd != cmd_lower:
            log.error("TelegramBot command '%s' contains uppercase letters, Telegram API requires lowercase. "
                      "Automatically converting to '%s'.", cmd, cmd_lower)
            cmd = cmd_lower

        if cmd in known_commands:
            raise KeyError(f'TelegramBot command {cmd} is duplicated')

        # Allow only alnum and underscores as cmds
        if not cmd.replace('_', '').isalnum():
            raise KeyError(f'TelegramBot command {cmd} is not alphanumeric')

        # Ensure order of known_commands is the same as the order expected when unpacking, so that it works with
        # either tuples or dict items
        known_commands[cmd] = {'cmd': cmd, 'descr': descr, 'cb': cb}
        fmt_cmds.append({'command': cmd, 'description': descr})

    return known_commands, str(json.dumps(fmt_cmds))


def _telegram_sanitize_message(msg, accepted_chat_ids):
    """ Extract and validate the 'message' field from a Telegram update.
    Returns the inner message dict, or None if it should be skipped.
    Raises TelegramUnauthorizedBotAccess if the sender is not in accepted_chat_ids. """
    if 'message' not in msg:
        log.debug('Ignoring non message update %s', msg)
        return None

    msg = msg['message']
    if 'chat' not in msg or 'id' not in msg['chat'] or 'from' not in msg or 'id' not in msg['from']:
        log.info(
            "Dropping dangerous looking message, can't find 'from' and 'chat' fields",
            msg)
        return None

    if not msg['from']['id'] in accepted_chat_ids:
        log.info('Unauthorized Telegram bot access detected %s', msg)
        smsg = json.dumps(msg)
        raise TelegramUnauthorizedBotAccess(smsg)

    return msg


def _telegram_sanitize_user_message(msg, known_cmds, accepted_chat_ids, try_parse_msg_as_cmd=False):
    msg = _telegram_sanitize_message(msg, accepted_chat_ids)
    if msg is None:
        return None

    if 'text' not in msg:
        log.debug('Ignoring message/thread metadata update %s', msg)
        return None

    if len(msg['text']) > _MAX_USER_MESSAGE_LEN:
        log.debug(
            'Message from user %s is longer than %s, discarding message',
            msg['from']['first_name'],
            _MAX_USER_MESSAGE_LEN)
        return None

    if try_parse_msg_as_cmd:
        maybe_cmd = msg['text'].split()
        if len(maybe_cmd) > 0:
            maybe_cmd = maybe_cmd[0]
        else:
            maybe_cmd = None
        if maybe_cmd is not None and maybe_cmd in known_cmds:
            msg['text'] = '/' + msg['text']

    cmd = None
    cmd_args = None
    if msg['text'][0] == '/':
        # Looks like a command
        toks = msg['text'].split(' ')
        if len(toks) > _MAX_USER_CMD_TOKS:
            log.debug(
                'Command from user %s has more than %s tokens, discarding message',
                msg['from']['first_name'],
                _MAX_USER_CMD_TOKS)
            return None

        cmd = toks[0]
        cmd = cmd[1:]  # Skip initial / of '/cmd'
        if cmd not in known_cmds:
            log.debug(
                'User %s requested unknown command %s, discarding message',
                msg['from']['first_name'],
                cmd)
            return None

        cmd_args = toks[1:]

    # Return only fields that look safe to parse
    return {
        'from': msg['from'],
        'chat': msg['chat'],
        'text': msg['text'],
        'cmd': cmd,
        'cmd_args': cmd_args,
    }


def _telegram_sanitize_voice_message(msg, accepted_chat_ids):
    msg = _telegram_sanitize_message(msg, accepted_chat_ids)
    if msg is None:
        return None

    if 'voice' in msg:
        voice = msg['voice']
        return {
            'from': msg['from'],
            'chat': msg['chat'],
            'type': 'voice',
            'file_id': voice['file_id'],
            'mime_type': voice.get('mime_type', 'audio/ogg'),
            'duration': voice.get('duration'),
        }
    elif 'audio' in msg:
        audio = msg['audio']
        return {
            'from': msg['from'],
            'chat': msg['chat'],
            'type': 'audio',
            'file_id': audio['file_id'],
            'mime_type': audio.get('mime_type', 'audio/mpeg'),
            'duration': audio.get('duration'),
        }

    return None


class TelegramBot:
    """ Simple Telegram wrapper to send messages, receive chats, etc """

    def __init__(
            self,
            tok,
            accepted_chat_ids,
            terminate_on_unauthorized_access=False,
            try_parse_msg_as_cmd=False,
            on_bot_received_non_cmd_message=None,
            on_bot_received_command=None,
            on_bot_received_voice_message=None):
        """
        Create a Telegram API wrapper.
        Register a bot @ https://telegram.me/BotFather then use the received token here
        """
        self._tok = tok
        self._api_base = f'https://api.telegram.org/bot{tok}'
        self._updates_offset = None
        self._known_commands = {}
        self._accepted_chat_ids = accepted_chat_ids
        self._try_parse_msg_as_cmd = try_parse_msg_as_cmd
        self._on_bot_received_non_cmd_message = on_bot_received_non_cmd_message
        self._on_bot_received_command = on_bot_received_command
        self._on_bot_received_voice_message = on_bot_received_voice_message

        # If an unauthorized access is detected, a file will be created - and then every time this service is instanciated,
        # an exception will be thrown
        self._terminate_on_unauthorized_access = terminate_on_unauthorized_access
        self._app_tainted_marker_file = './telegram_unauthorized_access_marker'
        if os.path.exists(self._app_tainted_marker_file):
            log.critical(
                "App tainted, refusing to start. Check %s",
                self._app_tainted_marker_file)
            os.kill(os.getpid(), 9)

        self.bot_info = _telegram_get(f'{self._api_base}/getMe')
        if not self.bot_info['is_bot']:
            log.error(
                "Telegram says the account under control isn't a bot, things may not work")

    def set_bot_name(self, bot_name):
        """ Replaces the name for this bot """
        return _telegram_post(
            f'{self._api_base}/setMyName',
            data={
                'name': bot_name})

    def set_bot_description(self, descr):
        """ Replaces the description for this bot """
        return _telegram_post(
            f'{self._api_base}/setMyDescription',
            data={
                'description': descr})

    def set_commands(self, cmds):
        """ Replaces the commands available to users of this bot """
        self._known_commands, fmt_cmds = _validate_telegram_cmds(cmds)
        return _telegram_get(
            f'{self._api_base}/setMyCommands',
            data={
                'commands': fmt_cmds})

    def add_commands(self, cmds):
        """ Adds new to the commands available to users of this bot """
        new_cmds, _ = _validate_telegram_cmds(cmds)
        for cmd in new_cmds:
            if cmd in self._known_commands:
                log.warning("Registering command '%s' replaces old command", cmd)
        self._known_commands.update(new_cmds)
        return self.set_commands(self._known_commands)

    def send_message(self, chat_id, text, disable_notifications=False):
        """ Send a text message to chat_id, or throw """
        if len(str(text).strip()) == 0:
            raise TelegramApiError("Can't send an empty text message")
        msg = _telegram_post(
            f'{self._api_base}/sendMessage',
            data={
                'chat_id': int(chat_id),
                'disable_notification': disable_notifications,
                'text': text})
        if 'message_id' not in msg:
            raise TelegramApiError(
                f'Failed to send message to chat {chat_id}: {msg}')

    def send_photo(self, *a, **kw):
        """ Send a photo to a chat """
        return self._send_file('sendPhoto', *a, **kw)

    def send_video(self, *a, **kw):
        """ Send a video to a chat """
        return self._send_file('sendVideo', *a, **kw)

    def _send_file(
            self,
            media_type,
            chat_id,
            fpath,
            caption=None,
            disable_notifications=False):
        """ Send a photo or video to chat_id, or throw. fpath should be a path to a local file """
        if media_type == 'sendPhoto':
            file = {'photo': open(fpath, 'rb')}
        elif media_type == 'sendVideo':
            if not fpath.endswith('.mp4'):
                raise ValueError(f'Telegram video file names must end in .mp4 ({fpath})')
            file = {'video': open(fpath, 'rb')}
        else:
            raise KeyError(f'Unknown or unsupported media type {media_type} for TelegramBot bot')

        msg = _telegram_post(
            f'{self._api_base}/{media_type}',
            data={
                'chat_id': int(chat_id),
                'disable_notification': disable_notifications,
                'caption': str(caption) if caption is not None else ''},
            files=file)
        if 'message_id' not in msg:
            raise TelegramApiError(
                f'Failed to send message to chat {chat_id}: {msg}')
        return True

    def _handle_unauthorized_access(self, ex):
        """ Notify accepted chats about unauthorized access and optionally terminate """
        if self._terminate_on_unauthorized_access:
            with open(self._app_tainted_marker_file, 'x', encoding="utf-8") as fp:
                fp.write(f'Unauthorized access to bot {ex}')
        for cid in self._accepted_chat_ids:
            self.send_message(cid, f'Unauthorized access to bot {ex}')
        # Terminating here means the message will remain unprocessed forever, and the
        # service will continue dying if restarted (as long as the message remains in the
        # Telegram servers)
        if self._terminate_on_unauthorized_access:
            os.kill(os.getpid(), 9)
            time.sleep(2)
            log.error("Failed to kill process after unauthorized access")
            while True:
                time.sleep(1)

    def download_file(self, file_id, dest_path):
        """ Download a file from Telegram servers to dest_path """
        result = _telegram_get(
            f'{self._api_base}/getFile',
            params={'file_id': file_id})
        file_path = result['file_path']
        download_url = f'https://api.telegram.org/file/bot{self._tok}/{file_path}'
        resp = requests.get(download_url)
        if resp.status_code != 200:
            raise TelegramHttpError(
                f'Failed to download file {file_id}: status {resp.status_code}')
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, 'wb') as fp:
            fp.write(resp.content)

    def poll_updates(self):
        """ Poll Telegram for events for this bot. Will call the installed command callback, if possible, or
        on_bot_received_non_cmd_message if not when a message is available/pending. Will ignore all other updates. """
        max_update_id = 0
        updates_prcd = 0
        for update in _telegram_get(f'{self._api_base}/getUpdates', params=self._updates_offset):
            try:
                max_update_id = max(max_update_id, int(update['update_id']) + 1)
            except BaseException:
                log.debug('Failed to parse Telegram update %s', update, exc_info=True)
                continue

            # First try to parse a voice message; if it contains voice then skip the general message parsing
            if self._on_bot_received_voice_message:
                try:
                    voice_msg = _telegram_sanitize_voice_message(update, self._accepted_chat_ids)
                except TelegramUnauthorizedBotAccess as ex:
                    voice_msg = None
                    self._handle_unauthorized_access(ex)

                if voice_msg is not None:
                    try:
                        self._on_bot_received_voice_message(voice_msg)
                    except BaseException:
                        log.error('Error processing voice message', exc_info=True)
                    updates_prcd += 1
                    continue

            try:
                msg = _telegram_sanitize_user_message(
                    update, self._known_commands, self._accepted_chat_ids, self._try_parse_msg_as_cmd)
            except TelegramUnauthorizedBotAccess as ex:
                self._handle_unauthorized_access(ex)
                msg = None

            if msg is None:
                continue
            elif msg['cmd'] is not None:
                try:
                    if self._on_bot_received_command:
                        self._on_bot_received_command(msg)
                    cb = self._known_commands[msg['cmd']]['cb']
                    cb(self, msg)
                except BaseException:
                    # Swallow all errors: if processing fails, we should continue from the next one,
                    # failing here means we'd retry them forever
                    log.error(
                        'User error processing Telegram command %s',
                        msg['cmd'],
                        exc_info=True)
            else:
                if self._on_bot_received_non_cmd_message:
                    self._on_bot_received_non_cmd_message(msg)
                else:
                    log.error("TelegramBot: Ignoring received non-command message: %s", msg)

            updates_prcd += 1

        self._updates_offset = {'offset': max_update_id}
        return updates_prcd


class TelegramLongpollBot(ABC):
    """ Creates a Telegram bot that will poll for updates. On connect failure, will
    ignore and try to create a new bot next round (to work around rate limits) """

    def __init__(
            self,
            tok,
            accepted_chat_ids,
            short_poll_interval_secs,
            long_poll_interval_secs,
            cmds=[],
            bot_name=None,
            bot_descr=None,
            message_history_len=50,
            terminate_on_unauthorized_access=False,
            try_parse_msg_as_cmd=False,
            scheduler=None):
        """ See TelegramBot """
        self._t = None
        self._cmds_set = False
        self._meta_set = False
        self._tok = tok
        self._accepted_chat_ids = accepted_chat_ids
        self._terminate_on_unauthorized_access = terminate_on_unauthorized_access
        self._try_parse_msg_as_cmd = try_parse_msg_as_cmd

        # Keep the history here instead of the parent object, so it persists over reconnects
        self._message_history = deque(maxlen=message_history_len)

        # State for poll frequency control
        self._short_poll_period_secs = short_poll_interval_secs
        self._long_poll_period_secs = long_poll_interval_secs
        self._current_poll_period = self._short_poll_period_secs
        self._polls_with_no_cmds = 0
        self._polls_with_no_cmds_before_reducing_freq = 120 / self._short_poll_period_secs

        self._commands, _ = _validate_telegram_cmds(cmds)
        self._bot_name = bot_name
        self._bot_descr = bot_descr

        if scheduler is not None:
            self._scheduler = scheduler
        else:
            self._scheduler = BackgroundScheduler()
            self._scheduler.start()
        self._poll_job = self._scheduler.add_job(
            func=self._poll_updates,
            trigger="interval",
            seconds=self._current_poll_period,
            next_run_time=datetime.now())

    def get_history(self):
        return self._message_history

    def _poll_updates(self):
        self.connect()
        if self._t is None:
            return

        try:
            msg_cnt = self._t.poll_updates()
        except requests.exceptions.ConnectionError as ex:
            msg_cnt = 0
            log.info(
                'TelegramLongpollBot: We seem to be offline, will try to connect later...')

        self._maybe_update_poll_frequency(msg_cnt)

    def _maybe_update_poll_frequency(self, last_poll_msg_cnt):
        if last_poll_msg_cnt != 0:
            self._polls_with_no_cmds = 0
        else:
            self._polls_with_no_cmds += 1

        needs_resched = False
        if self._polls_with_no_cmds < self._polls_with_no_cmds_before_reducing_freq and self._current_poll_period != self._short_poll_period_secs:
            # We received a cmd after a period of inactivity: increase poll freq
            needs_resched = True
            self._current_poll_period = self._short_poll_period_secs
        elif self._polls_with_no_cmds >= self._polls_with_no_cmds_before_reducing_freq and self._current_poll_period != self._long_poll_period_secs:
            # No commands received after inactivity period, decrease poll freq
            needs_resched = True
            self._current_poll_period = self._long_poll_period_secs
            log.info("User inactive: reducing frequency of polling to %s", self._current_poll_period)

        if needs_resched:
            self._poll_job.reschedule(
                trigger="interval",
                seconds=self._current_poll_period)

    def connect(self):
        self._build_base_bot()
        self._set_cmds()
        # Less important, if this fails it can be retried some time later
        self._set_meta()

    def _build_base_bot(self):
        """ Requests bot to connect, if not connected yet """
        if self._t is not None:
            return

        try:
            self._t = TelegramBot(
                self._tok,
                self._accepted_chat_ids,
                terminate_on_unauthorized_access=self._terminate_on_unauthorized_access,
                try_parse_msg_as_cmd=self._try_parse_msg_as_cmd,
                on_bot_received_non_cmd_message=self._on_bot_received_non_cmd_message,
                on_bot_received_command=self._on_bot_received_command,
                on_bot_received_voice_message=self._on_bot_received_voice_message)
            log.info('Connected to Telegram bot %s', self._t.bot_info['first_name'])
        except TelegramRateLimitError:
            log.warning('Telegram API rate limit, will try to connect later...')
        except requests.exceptions.ConnectionError as ex:
            log.warning(
                'TelegramLongpollBot: We seem to be offline, will try to connect later...')

    def _set_cmds(self):
        if self._cmds_set:
            return
        try:
            if self._commands is not None:
                self._t.set_commands(self._commands)
            self._cmds_set = True
        except TelegramRateLimitError:
            log.info('Telegram API rate limit, will set commands later...')

    def _set_meta(self):
        if self._meta_set:
            return
        # This isn't critical, so try only once
        self._meta_set = True
        try:
            if self._bot_name is not None:
                self._t.set_bot_name(self._bot_name)
            if self._bot_descr is not None:
                self._t.set_bot_description(self._bot_descr)
        except TelegramRateLimitError:
            log.info('Telegram API rate limit, bot metadata not set...')

    def add_commands(self, cmds):
        new_cmds, _ = _validate_telegram_cmds(cmds)
        self._commands.update(new_cmds)
        self.connect()
        if self._t is None:
            log.warning("Can't add new commands, Telegram not connected. Will add them once connected")
            return
        self._t.add_commands(cmds)

    def _on_bot_received_command(self, msg):
        self._message_history.append({
            'timestamp': datetime.now().isoformat(),
            'direction': 'received',
            'message': msg
        })

    def _on_bot_received_non_cmd_message(self, msg):
        self._message_history.append({
            'timestamp': datetime.now().isoformat(),
            'direction': 'received',
            'message': msg
        })
        self.on_bot_received_non_cmd_message(msg)

    @abstractmethod
    def on_bot_received_non_cmd_message(self, msg):
        """ Bot received a message. You should probably override this method. """
        print('TelegramLongpollBot has msg, but you should override this method', msg)

    def _on_bot_received_voice_message(self, msg):
        self._message_history.append({
            'timestamp': datetime.now().isoformat(),
            'direction': 'received',
            'message': msg
        })
        self.on_bot_received_voice_message(msg)

    def on_bot_received_voice_message(self, msg):
        """ Bot received a voice/audio message. Override to handle. """
        log.warning("TelegramLongpollBot received voice message but no handler is installed")

    def download_file(self, file_id, dest_path):
        """ Download a file from Telegram servers """
        self.connect()
        if self._t is None:
            log.error('Skipping request to download_file, Telegram not connected')
            return
        self._t.download_file(file_id, dest_path)

    def send_photo(self, *a, **kw):
        self.connect()
        if self._t is None:
            log.error('Skipping request to send_photo, Telegram not connected')
            return
        self._message_history.append(mk_log_sent_msg(*a, **kw))
        self._t.send_photo(*a, **kw)

    def send_video(self, *a, **kw):
        self.connect()
        if self._t is None:
            log.error('Skipping request to send_video, Telegram not connected')
            return
        self._message_history.append(mk_log_sent_msg(*a, **kw))
        self._t.send_video(*a, **kw)

    def send_message(self, *a, **kw):
        self.connect()
        if self._t is None:
            log.error('Skipping request to send message, Telegram not connected')
            return
        self._message_history.append(mk_log_sent_msg(*a, **kw))
        self._t.send_message(*a, **kw)

