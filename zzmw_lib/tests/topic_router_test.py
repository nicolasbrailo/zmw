import unittest
from types import SimpleNamespace

from zzmw_lib.z2m.topic_router import Z2MTopicRouter


def make_thing(name, real_name=None, address='0x0000000000000001', z2m_topic='net_a'):
    """ The only attributes of a thing the router uses """
    return SimpleNamespace(name=name, real_name=real_name or name, address=address, z2m_topic=z2m_topic)


class Recorder:
    """ A callback that records how it was called """
    def __init__(self):
        self.calls = []

    def __call__(self, subtopic, payload):
        self.calls.append((subtopic, payload))


class TestZ2MTopicRouter(unittest.TestCase):
    def setUp(self):
        self.router = Z2MTopicRouter()

    def test_dispatch_to_callback(self):
        cb = Recorder()
        self.router.add('net_a', 'Lamp', cb)
        self.assertTrue(self.router.dispatch('net_a', 'Lamp', {'state': 'ON'}))
        self.assertEqual(cb.calls, [('Lamp', {'state': 'ON'})])

    def test_dispatch_without_callbacks(self):
        self.assertFalse(self.router.dispatch('net_a', 'Lamp', {}))

    def test_callbacks_only_get_their_network(self):
        cb = Recorder()
        self.router.add('net_a', 'Lamp', cb)
        self.assertFalse(self.router.dispatch('net_b', 'Lamp', {}))
        self.assertEqual(cb.calls, [])

    def test_several_callbacks_per_topic(self):
        first, second = Recorder(), Recorder()
        self.router.add('net_a', 'Lamp', first)
        self.router.add('net_a', 'Lamp', second)
        self.router.dispatch('net_a', 'Lamp', {})
        self.assertEqual((len(first.calls), len(second.calls)), (1, 1))

    def test_callbacks_can_add_rules_while_dispatching(self):
        late = Recorder()
        self.router.add('net_a', 'Lamp', lambda _t, _p: self.router.add('net_a', 'Lamp', late))
        self.router.dispatch('net_a', 'Lamp', {})
        self.assertEqual(late.calls, [])
        self.router.dispatch('net_a', 'Lamp', {})
        self.assertEqual(len(late.calls), 1)


class TestZ2MTopicRouterBridge(unittest.TestCase):
    def setUp(self):
        self.router = Z2MTopicRouter()
        self.devices = Recorder()
        self.router.add_bridge_rules('net_a', self.devices)

    def test_device_lists(self):
        self.router.dispatch('net_a', 'bridge/devices', [{'friendly_name': 'Lamp'}])
        self.assertEqual(self.devices.calls, [('bridge/devices', [{'friendly_name': 'Lamp'}])])

    def test_other_bridge_messages_are_ignored(self):
        for subtopic in ('bridge/state', 'bridge/extensions', 'bridge/logging', 'bridge/info', 'bridge/config',
                         'bridge/converters', 'bridge/definitions', 'bridge/event',
                         'bridge/response/device/rename', 'bridge/response/health_check'):
            with self.subTest(subtopic=subtopic):
                self.assertTrue(self.router.dispatch('net_a', subtopic, {}))
        self.assertEqual(self.devices.calls, [])

    def test_bridge_rules_are_per_network(self):
        self.assertFalse(self.router.dispatch('net_b', 'bridge/devices', []))
        self.assertFalse(self.router.dispatch('net_b', 'bridge/state', {}))

    def test_groups_are_ignored_in_their_network(self):
        self.router.dispatch('net_a', 'bridge/groups', [{'id': 7}])
        self.assertTrue(self.router.dispatch('net_a', '7/', {}))
        self.assertTrue(self.router.dispatch('net_a', '7/availability', {}))
        self.assertFalse(self.router.dispatch('net_b', '7/availability', {}))

    def test_malformed_group(self):
        with self.assertLogs('Z2M', level='ERROR'):
            self.router.dispatch('net_a', 'bridge/groups', [{'no_id': 7}])


class TestZ2MTopicRouterThings(unittest.TestCase):
    def setUp(self):
        self.router = Z2MTopicRouter()
        self.cb = Recorder()
        self.availability = Recorder()

    def test_thing_topics(self):
        self.router.add_thing(make_thing('Lamp'), self.cb, self.availability)
        for subtopic in ('Lamp', 'Lamp/set', '0x0000000000000001', '0x0000000000000001/set'):
            self.router.dispatch('net_a', subtopic, {'state': 'ON'})
        self.assertEqual([t for t, _ in self.cb.calls],
                         ['Lamp', 'Lamp/set', '0x0000000000000001', '0x0000000000000001/set'])
        self.assertEqual(self.availability.calls, [])

    def test_thing_availability_topics(self):
        self.router.add_thing(make_thing('Lamp'), self.cb, self.availability)
        self.router.dispatch('net_a', 'Lamp/availability', {'state': 'offline'})
        self.router.dispatch('net_a', '0x0000000000000001/availability', {'state': 'online'})
        self.assertEqual(len(self.availability.calls), 2)
        self.assertEqual(self.cb.calls, [])

    def test_aliased_thing_gets_its_real_name_topics(self):
        self.router.add_thing(make_thing('OfficeLamp', real_name='Oficina'), self.cb, self.availability)
        self.router.dispatch('net_a', 'Oficina', {})
        self.router.dispatch('net_a', 'Oficina/set', {})
        self.router.dispatch('net_a', 'Oficina/availability', {})
        self.assertEqual(len(self.cb.calls), 2)
        self.assertEqual(len(self.availability.calls), 1)

    def test_coinciding_topics_are_registered_once(self):
        # Z2M names unnamed devices after their address: name, real_name and address are the same topic
        addr = '0x0000000000000001'
        self.router.add_thing(make_thing(addr, address=addr), self.cb, self.availability)
        for subtopic in (addr, f'{addr}/set', f'{addr}/availability'):
            self.router.dispatch('net_a', subtopic, {})
        self.assertEqual(len(self.cb.calls), 2)
        self.assertEqual(len(self.availability.calls), 1)

    def test_thing_topics_are_in_its_own_network(self):
        self.router.add_thing(make_thing('Lamp', z2m_topic='net_b'), self.cb, self.availability)
        self.assertFalse(self.router.dispatch('net_a', 'Lamp', {}))
        self.assertTrue(self.router.dispatch('net_b', 'Lamp', {}))

    def test_ignored_thing(self):
        self.router.ignore_thing(make_thing('Sensor'))
        for subtopic in ('Sensor', 'Sensor/set', 'Sensor/availability', '0x0000000000000001'):
            with self.subTest(subtopic=subtopic):
                self.assertTrue(self.router.dispatch('net_a', subtopic, {}))


if __name__ == '__main__':
    unittest.main()
