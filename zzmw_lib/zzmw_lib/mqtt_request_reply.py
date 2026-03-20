"""Thread-safe MQTT request-reply helper.

Serializes concurrent requests that expect the same reply subtopic, so one
reply cannot be consumed by the wrong waiter.
"""
import itertools
import threading

from .logs import build_logger

log = build_logger("MqttRequestReply")


class MqttRequestReply:
    """Manage in-flight MQTT request-reply pairs.

    Usage::

        self._rr = MqttRequestReply(self.message_svc)

        # In on_dep_published_message:
        if self._rr.on_reply(subtopic, payload):
            return

        # To send a request and wait:
        result = self._rr.request("SvcName", "cmd", {"key": "val"},
                                  "cmd_reply", timeout=5)
    """

    def __init__(self, send_fn):
        """
        Args:
            send_fn: callable(service, command, payload) that publishes
                     an MQTT message to a dependency (e.g. self.message_svc).
        """
        self._send = send_fn
        self._seq = itertools.count(1)
        # {reply_subtopic: (seq, threading.Event, [result])}
        self._pending = {}
        self._pending_lock = threading.Lock()
        # One lock per reply_subtopic to serialize concurrent requests
        self._request_locks = {}
        self._request_locks_lock = threading.Lock()

    def request(self, service, command, payload, reply_subtopic, timeout):
        """Send an MQTT command and block until the reply arrives or timeout.

        Concurrent requests waiting for the same reply_subtopic are serialized
        so that each reply is consumed by the correct waiter.

        Returns the reply payload, or None on timeout.
        """
        seq = next(self._seq)
        lock = self._get_request_lock(reply_subtopic)
        with lock:
            event = threading.Event()
            result = [None]
            with self._pending_lock:
                self._pending[reply_subtopic] = (seq, event, result)
            try:
                log.info("[rr#%d] %s/%s -> waiting on %s (timeout=%ds)",
                         seq, service, command, reply_subtopic, timeout)
                self._send(service, command, payload)
                if event.wait(timeout=timeout):
                    log.info("[rr#%d] %s/%s -> reply received", seq, service, command)
                    return result[0]
                log.warning("[rr#%d] %s/%s timed out after %ds",
                            seq, service, command, timeout)
                return None
            finally:
                with self._pending_lock:
                    self._pending.pop(reply_subtopic, None)

    def on_reply(self, subtopic, payload):
        """Dispatch an incoming message to a pending waiter.

        Call this from on_dep_published_message.  Returns True if the message
        was consumed by a pending request, False otherwise.
        """
        with self._pending_lock:
            pending = self._pending.get(subtopic)
            if pending is not None:
                log.info("[rr#%d] matched reply on %s", pending[0], subtopic)
                pending[2][0] = payload
                pending[1].set()
                return True
        return False

    def _get_request_lock(self, reply_subtopic):
        with self._request_locks_lock:
            if reply_subtopic not in self._request_locks:
                self._request_locks[reply_subtopic] = threading.Lock()
            return self._request_locks[reply_subtopic]
