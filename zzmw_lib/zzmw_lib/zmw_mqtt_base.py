from abc import ABC, abstractmethod
from .logs import build_logger
from paho.mqtt import publish as mqtt_bcast
import json
import logging
from datetime import datetime, date
import paho.mqtt.client as mqtt
import threading

# Configure third-party library log levels (they use root logger's handlers)
logging.getLogger('paho').setLevel(logging.INFO)
logging.getLogger("tzlocal").setLevel(logging.ERROR)
logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
logging.getLogger("apscheduler.scheduler").setLevel(logging.ERROR)

log = build_logger("ZmwMqtt", logging.INFO)

class ZmwMqttBase(ABC):
    """ Base ZmwMqtt client for ZmwServices: announces to other clients when this client is up, and provides access
    to mqtt topics """

    @abstractmethod
    def get_service_meta(self):
        """ Metadata for this service - this will be automatically defined by the service_runner, in most cases """
        pass

    def __init__(self, cfg):
        # Global topic to announce services are alive
        self._global_svc_discovery_ping_topic = "svc_ping_bcast"
        self._global_svc_discovery_announce_topic = "svc_announce_bcast"
        self._global_svc_discovery_leaving_topic = "svc_leaving_bcast"

        # Mqtt client setup
        self._mqtt_ip = cfg.get('mqtt_ip', 'localhost')
        self._mqtt_port = cfg.get('mqtt_port', 1883)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        # self.client.enable_log(log=log)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_unsubscribe = self._on_unsubscribe
        self.client.on_message = self._on_message
        self.bg_thread = None

        # Mqtt topics we'll subscribe to
        self._topics_with_cb_lock = threading.Lock()
        self._topics_with_cb = {}

    def loop_forever(self):
        """ Connects to MQTT and starts the net loop. Doesn't return until stop is called """
        log.info('Connecting to MQTT broker [%s]:%d in client only mode...', self._mqtt_ip, self._mqtt_port)
        self.client.connect(self._mqtt_ip, self._mqtt_port, 10)
        self.client.loop_forever()

    def loop_forever_bg(self):
        """ Launches a bg thread that calls self.loop_forever """
        self.bg_thread = threading.Thread(target=self.loop_forever)
        self.bg_thread.start()

    def stop(self):
        """ Starts disconnect process """
        log.info('Requesting MQTT client disconnect...')

        # Announce this service is leaving
        self.broadcast(self._global_svc_discovery_leaving_topic, self.get_service_meta())

        self.client.disconnect()
        if self.bg_thread:
            self.bg_thread.join()

    def broadcast(self, topic, msg):
        """ JSONises and broadcasts a message to MQTT """
        def _serialize(obj):
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")
        msg = json.dumps(msg, default=_serialize)
        mqtt_bcast.single(qos=1, hostname=self._mqtt_ip, port=self._mqtt_port, topic=topic, payload=msg)

    def on_service_discovery_ping(self):
        """ Global request for service announcements """
        self.broadcast(self._global_svc_discovery_announce_topic, self.get_service_meta())

    def _on_connect(self, client, _userdata, _flags, ret_code, _props):
        if ret_code == 0:
            log.info('Connected to MQTT broker [%s]:%d', self._mqtt_ip, self._mqtt_port)
        else:
            log.warning('Connected to MQTT broker [%s]:%d with error code %d.', 
                        self._mqtt_ip, self._mqtt_port, ret_code)

        client.subscribe(self._global_svc_discovery_ping_topic, qos=1)

        self._topics_with_cb_lock = threading.Lock()
        with self._topics_with_cb_lock:
            for topic in self._topics_with_cb.keys():
                try:
                    client.subscribe(f'{topic}/#', qos=1)
                except ValueError:
                    log.error("Invalid MQTT subscription filter, skipping: '%s/#'", topic)

        # Announce we're up and running
        log.info('Running MQTT listener thread, client mode only')
        self.on_service_discovery_ping()

    def _on_disconnect(self, _client, _userdata, _disconnect_flags, _ret_code, _props):
        log.info('Disconnected from MQTT broker [%s]:%d', self._mqtt_ip, self._mqtt_port)

    def _on_subscribe(self, client, _userdata, _mid, _reason_code, _props):
        log.debug('MQTT client [%s]:%d subscribed', self._mqtt_ip, self._mqtt_port)

    def _on_unsubscribe(self, client, _userdata, _mid, reason_code, _props):
        log.info('MQTT client [%s]:%d unsubscribed (reason %s)',
                 self._mqtt_ip, self._mqtt_port, str(reason_code))

    def subscribe_with_cb(self, topic, cb):
        with self._topics_with_cb_lock:
            if topic in self._topics_with_cb:
                log.warning(f"Topic {topic} already has a callback, will replace it")
            self._topics_with_cb[topic] = cb
            log.info("MQTT subscribing to '%s'", topic)
            # If not subscribed this is a noop, but it will be repeated when connecting
            try:
                self.client.subscribe(topic)
            except ValueError:
                log.error("Invalid MQTT subscription filter, skipping: '%s'", topic)

    def _on_message(self, _client, _userdata, msg):
        topic = msg.topic
        if topic.startswith(self._global_svc_discovery_ping_topic):
            return self.on_service_discovery_ping()

        try:
            parsed_msg = json.loads(msg.payload)
        except (TypeError, json.JSONDecodeError):
            log.warning(f"Ignoring non-json message with topic '%s'", topic)
            return

        try:
            for (t, cb) in self._topics_with_cb.items():
                if t[-2:] == '/#':
                    # This topic has an mqtt wildcard, it fininshes with 'topic/#'. Don't check the wildcard.
                    t = t[:-2]
                if topic.startswith(t):
                    subtopic = topic[len(t) + len('/'):]
                    return cb(subtopic, parsed_msg)
            # Fall-through: received unhandled message
        except Exception as ex:  # pylint: disable=broad-except
            log.critical(
                'Error on MQTT message handling. Topic %s, payload %s. '
                'Ex: {%s}', msg.topic, msg.payload, ex, exc_info=True)
            return

        log.error(f"Unhandeld message with topic '%s'", topic)

