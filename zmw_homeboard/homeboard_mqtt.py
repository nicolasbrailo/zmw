"""MQTT link to the homeboards: their state, and the commands we send them.
"""

import json
import logging
import os
import threading

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


def validate_homeboard_id(hb_id):
    if not isinstance(hb_id, str) or not hb_id:
        return None
    if any(c in hb_id for c in ('/', '#', '+')):
        return None
    return hb_id


def as_positive_int(v):
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


def as_year(v):
    """A year for the album filter: an int in 0..9999, where 0 means unbounded."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = int(v)
        except ValueError:
            return None
    if not isinstance(v, int):
        return None
    return v if 0 <= v <= 9999 else None


def as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ('1', 'true', 'yes', 'on'):
            return True
        if s in ('0', 'false', 'no', 'off'):
            return False
    return None


def _parse_json_object(prefix, what, raw_payload):
    """The payload as a dict, or None (logged) when it isn't a JSON object."""
    try:
        data = json.loads(raw_payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("Non-JSON %s for '%s': %r", what, prefix, raw_payload)
        return None
    if not isinstance(data, dict):
        log.warning("%s for '%s' is not a JSON object", what, prefix)
        return None
    return data


class HomeboardMqtt:
    """
    Talks to the homeboards over their own MQTT broker.

    Subscribes to the retained topics every homeboard publishes under its
    prefix (`availability` for online/offline, `state` for the device's state
    record, `state/displayed_photo`), plus the non-retained `doctor`
    telemetry, keeps the latest of each in memory, and publishes commands
    back.

    Callbacks run on the paho-mqtt loop thread, so callers doing non-trivial
    work in them (e.g. republishing on another bus) must mind thread safety.

    Lifecycle: construct, start() to connect, stop() to disconnect.
    """

    # Max payload size, about 1MB. In the homeboard, this is set slightly larger than 1MB; ideally
    # we'd catch failures here, not in the hb
    _MAX_PAYLOAD_LEN = 1024 * 1024

    # Retained topics a homeboard publishes under its prefix. Cleared as a
    # group when evicting a board, or the others would be replayed on
    # reconnect.
    _RETAINED_TOPICS = ('availability', 'state', 'state/displayed_photo')

    def __init__(self, mqtt_ip, mqtt_port, *,
                 on_device_state=None,
                 on_host_info=None,
                 on_online=None,
                 client_id_suffix=""):
        self._broker = (mqtt_ip, int(mqtt_port))
        self._on_device_state = on_device_state
        self._on_host_info = on_host_info
        self._on_online = on_online

        self._lock = threading.Lock()
        self._homeboards = {}
        # Prefixes whose retained `availability` record could not be parsed.
        # They never show up in list_homeboards(), so they're tracked here for
        # the janitor to evict.
        self._bad_availability = set()
        self._host_info = {}
        self._device_state = {}
        self._displayed_photos = {}
        # Latest `<prefix>/doctor` health telemetry per homeboard. Not retained,
        # so this stays empty until the doctor service publishes its next cycle.
        self._doctor = {}

        suffix = client_id_suffix or str(os.getpid())
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"zmw_homeboard_{suffix}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True
        ip, port = self._broker
        log.info("Connecting to homeboard MQTT broker [%s]:%s...", ip, port)
        self._client.connect_async(ip, port, 30)
        self._client.loop_start()

    def stop(self):
        if not self._started:
            return
        self._client.loop_stop()
        self._client.disconnect()
        self._started = False

    def _on_connect(self, client, _ud, _flags, ret_code, _props):
        if ret_code == 0:
            log.info("Connected to homeboard MQTT broker %s", self._broker)
        else:
            log.warning("Homeboard MQTT connect to %s returned rc=%s", self._broker, ret_code)
        # Every homeboard publishes "<prefix>/availability" retained, carrying
        # both the online/offline state and the host info (machine_id,
        # hostname, ip, ...) in a single JSON object. It's also the last will.
        # Subscribing to this wildcard lets us enumerate all registered prefixes.
        client.subscribe('+/availability', qos=0)
        # The device's state record. `+/state` only matches two levels, so it
        # doesn't overlap `state/displayed_photo`.
        client.subscribe('+/state', qos=0)
        client.subscribe('+/state/displayed_photo', qos=0)
        # Health/telemetry from the homeboard-doctor service (not retained).
        client.subscribe('+/doctor', qos=0)

    def _on_message(self, _client, _ud, msg):
        parts = msg.topic.split('/')
        prefix = parts[0]
        leaf = '/'.join(parts[1:])
        if leaf == 'availability':
            self._handle_availability(prefix, msg.payload)
        elif leaf == 'state':
            self._handle_device_state(prefix, msg.payload)
        elif leaf == 'state/displayed_photo':
            self._handle_displayed_photo(prefix, msg.payload)
        elif leaf == 'doctor':
            self._handle_doctor(prefix, msg.payload)

    def _handle_availability(self, prefix, raw_payload):
        # An empty retained payload is the broker replaying a deleted retained
        # record (e.g. the janitor cleared it). Drop all state for this prefix.
        if not raw_payload:
            with self._lock:
                self._homeboards.pop(prefix, None)
                self._host_info.pop(prefix, None)
                self._bad_availability.discard(prefix)
                # Doctor stats aren't retained (nothing to clear on the broker),
                # so drop the in-memory copy when the board is evicted.
                self._doctor.pop(prefix, None)
            log.info("Homeboard '%s' retained availability record cleared", prefix)
            return
        data = _parse_json_object(prefix, 'availability', raw_payload)
        state = data.get('state') if data is not None else None
        if state not in ('online', 'offline'):
            if data is not None:
                log.warning("Unexpected availability state %r for '%s'", state, prefix)
            with self._lock:
                self._bad_availability.add(prefix)
            return
        with self._lock:
            prev = self._homeboards.get(prefix)
            prev_info = self._host_info.get(prefix) or {}
            self._homeboards[prefix] = state
            self._host_info[prefix] = data
            self._bad_availability.discard(prefix)
        if prev != state:
            log.info("Homeboard '%s' is %s", prefix, state)
        # A device that restarts before the broker notices it went away goes
        # from online to online, with a new started_at: that's a new run too
        came_online = state == 'online' and (
            prev != 'online' or prev_info.get('started_at') != data.get('started_at'))
        if came_online and self._on_online is not None:
            self._on_online(prefix)
        if self._on_host_info is not None:
            self._on_host_info(prefix, data)

    def _handle_displayed_photo(self, prefix, raw_payload):
        if not raw_payload:
            with self._lock:
                self._displayed_photos.pop(prefix, None)
            return
        # Ignore state for prefixes we've never seen an availability record for: those
        # are stale/renamed retained records, and republishing them leaks ghost
        # homeboards onto downstream buses.
        if not self._is_known_homeboard(prefix):
            log.debug("Ignoring displayed_photo for unknown homeboard '%s'", prefix)
            return
        data = _parse_json_object(prefix, 'displayed_photo', raw_payload)
        if data is None:
            return
        with self._lock:
            self._displayed_photos[prefix] = data
        log.info("Homeboard '%s' displaying: %s", prefix, data.get('filename'))

    def _handle_device_state(self, prefix, raw_payload):
        if not raw_payload:
            with self._lock:
                self._device_state.pop(prefix, None)
            return
        if not self._is_known_homeboard(prefix):
            log.debug("Ignoring state record for unknown homeboard '%s'", prefix)
            return
        data = _parse_json_object(prefix, 'state record', raw_payload)
        if data is None:
            return
        # Kept as published: devices add keys of their own, and any value may
        # be null, so interpreting it is left to whoever reads it.
        with self._lock:
            self._device_state[prefix] = data
        if self._on_device_state is not None:
            self._on_device_state(prefix, data)

    def _handle_doctor(self, prefix, raw_payload):
        if not raw_payload:
            with self._lock:
                self._doctor.pop(prefix, None)
            return
        if not self._is_known_homeboard(prefix):
            log.debug("Ignoring doctor stats for unknown homeboard '%s'", prefix)
            return
        data = _parse_json_object(prefix, 'doctor stats', raw_payload)
        if data is None:
            return
        with self._lock:
            self._doctor[prefix] = data

    def list_homeboards(self):
        with self._lock:
            return [{
                "id": k,
                "state": v,
                "device_state": self._device_state.get(k),
                "displayed_photo": self._displayed_photos.get(k),
                "host_info": self._host_info.get(k),
                "doctor": self._doctor.get(k),
            } for k, v in sorted(self._homeboards.items())]

    def list_bad_availability(self):
        """Prefixes whose retained availability record we couldn't parse."""
        with self._lock:
            return sorted(self._bad_availability)

    def _is_known_homeboard(self, prefix):
        """Whether we've seen a valid `availability` record for this prefix."""
        with self._lock:
            return prefix in self._homeboards

    def clear_retained_state(self, hb_id):
        """Delete a homeboard's retained records from the broker.

        A zero-byte retained payload deletes the retained record for a topic.
        The broker also delivers it to us, and the handlers drop what we kept
        in memory for this homeboard.
        """
        hb_id = validate_homeboard_id(hb_id)
        if hb_id is None:
            return
        for topic in self._RETAINED_TOPICS:
            self._client.publish(f"{hb_id}/{topic}", payload=None, qos=0, retain=True)

    def _send_cmd(self, hb_id, service, command, payload="{}"):
        hb_id = validate_homeboard_id(hb_id)
        if hb_id is None:
            return False
        if len(payload) > self._MAX_PAYLOAD_LEN:
            raise ValueError(f"MQTT payload for '{hb_id}' too large ({len(payload)}) max is {self._MAX_PAYLOAD_LEN}")

        topic = f"{hb_id}/cmd/{service}/{command}"
        log_payload = payload if len(payload) <= 50 else payload[:50] + "..."
        log.info("Publishing '%s' (%s) to homeboard broker", topic, log_payload)
        info = self._client.publish(topic, payload, qos=0)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.error("Failed to publish '%s', rc=%s", topic, info.rc)
            return False
        return True

    def next(self, hb_id):
        return self._send_cmd(hb_id, 'ambience', 'next')

    def doorbell_ring(self, hb_id, rtsp_urls):
        """Tell the homeboard someone rang the doorbell, and where to watch the door.

        `rtsp_urls` maps a stream name ('main', 'sub') to its RTSP URL,
        credentials included; it may be empty if the camera reported none, and
        the ring is still sent. Entries that aren't rtsp:// strings are dropped.
        """
        if not isinstance(rtsp_urls, dict):
            return False
        streams = {name: url for name, url in rtsp_urls.items()
                   if isinstance(name, str) and isinstance(url, str) and url.startswith('rtsp://')}
        return self._send_cmd(hb_id, 'doorbell', 'ring', json.dumps({"rtsp_urls": streams}))

    def prev(self, hb_id):
        return self._send_cmd(hb_id, 'ambience', 'prev')

    def force_on(self, hb_id):
        return self._send_cmd(hb_id, 'presence', 'force_on')

    def force_off(self, hb_id):
        return self._send_cmd(hb_id, 'presence', 'force_off')

    def set_transition_time_secs(self, hb_id, secs):
        secs = as_positive_int(secs)
        if secs is None:
            return False
        return self._send_cmd(hb_id, 'ambience', 'set_transition_time_secs',
                              json.dumps({"secs": secs}))

    def announce(self, hb_id, timeout_secs, msg):
        timeout_secs = as_positive_int(timeout_secs)
        if timeout_secs is None:
            return False
        if not isinstance(msg, str):
            return False
        return self._send_cmd(hb_id, 'ambience', 'announce',
                              json.dumps({"timeout": timeout_secs, "msg": msg}))

    def announce_audio(self, hb_id, uri, volume=None, msg=None):
        """Tell the homeboard that the speakers started playing `uri`.

        `volume` is the 0-100 volume the speakers were asked to use, or None
        if they'll use their own default; it's left out of the payload then.
        `msg` is the text being spoken when the audio comes from a TTS
        request, and is left out when None or empty.
        """
        if not isinstance(uri, str) or not uri:
            return False
        if msg is not None and not isinstance(msg, str):
            return False
        payload = {"uri": uri}
        if msg:
            payload["msg"] = msg
        if volume is not None:
            volume = as_positive_int(volume)
            if volume is None or volume > 100:
                return False
            payload["volume"] = volume
        return self._send_cmd(hb_id, 'ambience', 'announce_audio', json.dumps(payload))

    def set_svg_overlay(self, hb_id, timeout_secs, svg):
        timeout_secs = as_positive_int(timeout_secs)
        if timeout_secs is None:
            return False
        if not isinstance(svg, str):
            return False
        return self._send_cmd(hb_id, 'ambience', 'set_svg_overlay',
                              json.dumps({"timeout": timeout_secs, "svg": svg}))

    def set_embed_qr(self, hb_id, enabled):
        enabled = as_bool(enabled)
        if enabled is None:
            return False
        return self._send_cmd(hb_id, 'photo_provider', 'set_embed_qr',
                              json.dumps({"on": enabled}))

    def set_target_size(self, hb_id, width, height):
        width = as_positive_int(width)
        height = as_positive_int(height)
        if not width or not height:
            return False
        return self._send_cmd(hb_id, 'photo_provider', 'set_target_size',
                              json.dumps({"w": width, "h": height}))

    def set_album_filter(self, hb_id, name='', exclude='', from_year=0, to_year=0):
        """Pick which albums the slideshow may draw pictures from.

        `name` and `exclude` are comma-separated glob patterns (`*`, `?`,
        everything else literal) matched case-insensitively against the whole
        album name; `exclude` wins over `name`. `from_year`/`to_year` bound the
        span of an album's pictures, 0 meaning unbounded, and the test is an
        overlap one, so a reversed range would select the albums straddling it
        rather than none -- we reject that instead.

        The payload replaces the whole filter on the device: calling this with
        no arguments clears it and brings every album back.
        """
        if not isinstance(name, str) or not isinstance(exclude, str):
            return False
        from_year = as_year(from_year)
        to_year = as_year(to_year)
        if from_year is None or to_year is None:
            return False
        if from_year and to_year and from_year > to_year:
            return False
        return self._send_cmd(hb_id, 'ambience', 'set_album_filter',
                              json.dumps({
                                  "name": name.strip(),
                                  "exclude": exclude.strip(),
                                  "from_year": from_year,
                                  "to_year": to_year,
                              }))
