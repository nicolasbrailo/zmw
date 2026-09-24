""" Tests for ZmwMqttBase topic -> callback dispatch. Z2MProxy depends on this dispatch to receive its messages. """
import json
import unittest
from types import SimpleNamespace

from zzmw_lib.zmw_mqtt_base import ZmwMqttBase


class _TestClient(ZmwMqttBase):
    def get_service_meta(self):
        return {}


class TestMqttDispatch(unittest.TestCase):
    def setUp(self):
        self.client = _TestClient({})
        self.calls = []

    def _sub(self, topic):
        self.client.subscribe_with_cb(topic, lambda sub, payload: self.calls.append((topic, sub, payload)))

    def _deliver(self, topic, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.client._on_message(None, None, SimpleNamespace(topic=topic, payload=raw))

    def test_subtopic_is_stripped(self):
        self._sub('zigbee2mqtt')
        self._deliver('zigbee2mqtt/bridge/devices', [1])
        self.assertEqual(self.calls, [('zigbee2mqtt', 'bridge/devices', [1])])

    def test_exact_topic_has_empty_subtopic(self):
        self._sub('zmw_thing_extras/Foo')
        self._deliver('zmw_thing_extras/Foo', {'a': 1})
        self.assertEqual(self.calls, [('zmw_thing_extras/Foo', '', {'a': 1})])

    def test_wildcard_subscription(self):
        self._sub('foo/#')
        self._deliver('foo/bar/baz', {})
        self.assertEqual(self.calls, [('foo/#', 'bar/baz', {})])

    def test_dispatches_to_matching_topic_only(self):
        self._sub('svc_a')
        self._sub('svc_b')
        self._deliver('svc_b/cmd', {})
        self.assertEqual(self.calls, [('svc_b', 'cmd', {})])

    def test_non_json_is_ignored(self):
        self._sub('zigbee2mqtt')
        with self.assertLogs('ZmwMqtt', level='WARNING'):
            self._deliver('zigbee2mqtt/foo', b'not json{')
        self.assertEqual(self.calls, [])

    def test_unhandled_topic_logs_error(self):
        self._sub('zigbee2mqtt')
        with self.assertLogs('ZmwMqtt', level='ERROR'):
            self._deliver('other/foo', {})
        self.assertEqual(self.calls, [])

    def test_cb_exception_is_contained(self):
        def _boom(_sub, _payload):
            raise RuntimeError('boom')
        self.client.subscribe_with_cb('zigbee2mqtt', _boom)
        with self.assertLogs('ZmwMqtt', level='CRITICAL'):
            self._deliver('zigbee2mqtt/foo', {})

    # Known bugs: matching is a raw string prefix, so a topic that is a prefix of another one steals its messages.
    # Step 1 of multiz2m.md fixes these; remove the expectedFailure markers then.

    @unittest.expectedFailure
    def test_sibling_topic_with_shared_prefix(self):
        self._sub('zigbee2mqtt')
        self._sub('zigbee2mqtt_foo')
        self._deliver('zigbee2mqtt_foo/bridge/devices', [1])
        self.assertEqual(self.calls, [('zigbee2mqtt_foo', 'bridge/devices', [1])])

    @unittest.expectedFailure
    def test_thing_extras_with_shared_name_prefix(self):
        self._sub('zmw_thing_extras/Foo')
        self._sub('zmw_thing_extras/FooBar')
        self._deliver('zmw_thing_extras/FooBar', {'a': 1})
        self.assertEqual(self.calls, [('zmw_thing_extras/FooBar', '', {'a': 1})])

    @unittest.expectedFailure
    def test_prefix_without_separator_is_unhandled(self):
        self._sub('zigbee2mqtt')
        self._deliver('zigbee2mqttX/foo', {})
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
