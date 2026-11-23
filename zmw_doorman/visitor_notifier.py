"""WhatsApp notifications for people at the door, from ZmwVisitorDetect's events.

One message per visit, preferably with a face: a session's on_person_detected starts a wait of
visitor_face_wait_secs; a face (identified or not) arriving in that time is sent at once, else the person picture
is sent when the wait ends. At night faces are never analysed, so the person picture goes out at once. A face
arriving after the person picture is sent as one follow-up (so is a second person, or an unknown face later
identified). The same person (visitor id, "unknown visitor" or "someone") isn't sent again within
visitor_notify_repeat_secs, so someone lingering at the door doesn't spam.

A newly discovered regular visitor (on_new_frequent_visitor) is announced separately, through send_new_visitor
(Telegram): it's rare, and says who to name in ZmwVisitorDetect's visitor_names.
"""
import threading
import time

from zzmw_lib.logs import build_logger

log = build_logger("VisitorNotifier")

# Follow-ups per session, after the first message
_MAX_FOLLOW_UPS = 1
# Sessions last at most a few minutes (ZmwVisitorDetect's max_session_s)
_FORGET_SESSION_SECS = 600

_PERSON = 'on_person_detected'
_NEW_VISITOR = 'on_new_frequent_visitor'
_FACE_EVENTS = ('on_face_identified', 'on_face_detected')


class _Session:
    def __init__(self, session_id, now):
        self.id = session_id
        self.started = now
        self.person = None        # its on_person_detected
        self.cancel_wait = None
        self.messages = 0         # sent (or suppressed as a repeat)
        self.who = set()          # who keys messaged in this session


class VisitorNotifier:
    def __init__(self, cfg, send_photo, schedule, on_sent=lambda session_id, text: None,
                 send_new_visitor=lambda path, text: None, now=time.time):
        """
        Args:
            cfg: Service config; the visitor_* keys are required (no defaults: KeyError at startup if missing)
            send_photo: fn(path, msg) that sends a photo to WhatsApp
            schedule: fn(delay_secs, callback) -> cancel fn
            on_sent: fn(session_id, text), after each message sent (eg for the door history)
            send_new_visitor: fn(path, text) that announces a new regular visitor (path may be None)
            now: Clock
        """
        self._wait_secs = cfg['visitor_face_wait_secs']
        self._repeat_secs = cfg['visitor_notify_repeat_secs']
        self._notify_injected = cfg['visitor_notify_injected']
        self._send_photo = send_photo
        self._on_sent = on_sent
        self._send_new_visitor = send_new_visitor
        self._schedule = schedule
        self._now = now
        self._lock = threading.Lock()
        self._sessions = {}       # session_id -> _Session
        self._last_sent = {}      # who key -> when

    def on_visitor_event(self, subtopic, msg):
        if subtopic != _PERSON and subtopic != _NEW_VISITOR and subtopic not in _FACE_EVENTS:
            return
        if not isinstance(msg, dict) or not msg.get('session_id'):
            log.error("Bad %s from ZmwVisitorDetect, no session_id: %s", subtopic, msg)
            return
        if msg.get('trigger') == 'injected' and not self._notify_injected:
            log.info("Not notifying %s from injected (test) session %s", subtopic, msg['session_id'])
            return
        if subtopic == _NEW_VISITOR:
            self._announce_new_visitor(msg)
            return
        with self._lock:
            now = self._now()
            self._sessions = {sid: s for sid, s in self._sessions.items()
                              if now - s.started < _FORGET_SESSION_SECS}
            sid = msg['session_id']
            session = self._sessions.setdefault(sid, _Session(sid, now))
            if subtopic == _PERSON:
                self._on_person(sid, session, msg)
            else:
                self._on_face(session, msg)

    def _announce_new_visitor(self, msg):
        name = msg.get('name') or msg.get('visitor_id')
        text = (f"New regular visitor: {name}, seen in {msg.get('visits')} visits on {msg.get('days')} days. "
                f"Name them in ZmwVisitorDetect's visitor_names ({msg.get('visitor_id')})")
        log.info("Announcing over Telegram: %s", text)
        self._send_new_visitor(msg.get('notify_img_path'), text)

    def _on_person(self, sid, session, msg):
        if session.person is not None or session.messages:
            return
        session.person = msg
        if msg.get('day_night') == 'night':
            # No faces at night: nothing to wait for
            self._send(session, 'someone', msg, "Someone is at the door")
            return
        session.cancel_wait = self._schedule(self._wait_secs, lambda: self._on_wait_over(sid))

    def _on_wait_over(self, sid):
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return
            session.cancel_wait = None
            if session.messages:
                return
            log.info("No face in %ss for session %s, sending the person picture", self._wait_secs, sid)
            self._send(session, 'someone', session.person, "Someone is at the door")

    def _on_face(self, session, msg):
        if msg.get('visitor_id'):
            who, text = msg['visitor_id'], f"{msg.get('name') or msg['visitor_id']} is at the door"
        else:
            who, text = 'unknown', "Unknown visitor at the door"
        if session.messages > _MAX_FOLLOW_UPS or who in session.who:
            return
        if session.cancel_wait is not None:
            session.cancel_wait()
            session.cancel_wait = None
        self._send(session, who, msg, text)

    def _send(self, session, who, msg, text):
        session.messages += 1
        session.who.add(who)
        now = self._now()
        if now - self._last_sent.get(who, -self._repeat_secs) < self._repeat_secs:
            log.info("Not sending '%s': sent less than %ss ago", text, self._repeat_secs)
            return
        img = msg.get('notify_img_path') or (session.person or {}).get('notify_img_path')
        if not img:
            log.warning("Can't send '%s': no notification image (is ZmwVisitorDetect's notification_img_dir set?)",
                        text)
            return
        self._last_sent[who] = now
        log.info("Visitor at the door, sending '%s' over WA", text)
        self._send_photo(img, text)
        self._on_sent(session.id, text)
