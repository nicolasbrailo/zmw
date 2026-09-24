from z2m_fixtures import get_a_lamp
from z2m_fixtures import get_contact_sensor
from z2m_fixtures import get_motion_sensor

import os
import signal
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from zzmw_lib.z2m.thing import create_virtual_thing
from zzmw_lib.z2m.z2mproxy import Z2MProxy

LAMP_ADDR = '0x847127fffecda276'


class FakeMqtt:
    """ Records subscriptions and broadcasts; lets tests deliver messages as if they came from the broker. Topics
    delivered through here are already stripped of the subscription prefix, like ZmwMqttBase does. """
    def __init__(self):
        self.subscriptions = {}
        self.broadcasts = []

    def subscribe_with_cb(self, topic, cb):
        self.subscriptions[topic] = cb

    def broadcast(self, topic, msg):
        self.broadcasts.append((topic, msg))

    def deliver(self, subtopic, payload, topic='zigbee2mqtt'):
        self.subscriptions[topic](subtopic, payload)


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, trigger, kwargs))


def make_proxy(**kwargs):
    mqtt = FakeMqtt()
    sched = FakeScheduler()
    proxy = Z2MProxy({}, mqtt, sched, **kwargs)
    return proxy, mqtt, sched


class TestZ2MProxyConstruction(unittest.TestCase):
    def test_subscribes_to_default_topic(self):
        _, mqtt, _ = make_proxy()
        self.assertEqual(list(mqtt.subscriptions.keys()), ['zigbee2mqtt'])

    def test_subscribes_to_custom_topic(self):
        _, mqtt, _ = make_proxy(topic='custom_z2m')
        self.assertEqual(list(mqtt.subscriptions.keys()), ['custom_z2m'])

    def test_schedules_connect_check(self):
        _, _, sched = make_proxy()
        self.assertEqual(len(sched.jobs), 1)
        _, trigger, kwargs = sched.jobs[0]
        self.assertEqual(trigger, 'date')
        self.assertIn('run_date', kwargs)

    def test_no_things_before_discovery(self):
        proxy, _, _ = make_proxy()
        self.assertEqual(proxy.get_thing_names(), [])


class TestZ2MProxyDiscovery(unittest.TestCase):
    def test_registers_published_devices(self):
        proxy, mqtt, _ = make_proxy()
        mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])
        self.assertEqual(set(proxy.get_thing_names()), {'Oficina', 'SensorPuertaEntrada'})
        self.assertEqual(proxy.get_thing('Oficina').thing_type, 'light')

    def test_uninteresting_devices_are_not_registered(self):
        proxy, mqtt, _ = make_proxy(cb_is_device_interesting=lambda t: t.thing_type == 'light')
        mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])
        self.assertEqual(proxy.get_thing_names(), ['Oficina'])

    def test_discovery_cb_first_then_subsequent(self):
        calls = []
        proxy, mqtt, _ = make_proxy(
            cb_on_z2m_network_discovery=lambda first, known: calls.append((first, set(known.keys()))))
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])
        self.assertEqual(calls, [
            (True, {'Oficina'}),
            (False, {'Oficina', 'SensorPuertaEntrada'}),
        ])

    def test_discovery_cb_known_things_are_the_registered_things(self):
        received = {}
        proxy, mqtt, _ = make_proxy(cb_on_z2m_network_discovery=lambda _first, known: received.update(known))
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        self.assertIs(received['Oficina'], proxy.get_thing('Oficina'))

    def test_republish_keeps_existing_thing_objects(self):
        # Services hold references to things (and attach callbacks to them), so a network republish must not
        # replace known things
        proxy, mqtt, _ = make_proxy()
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        lamp = proxy.get_thing('Oficina')
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        self.assertIs(proxy.get_thing('Oficina'), lamp)
        self.assertEqual(proxy.get_thing_names(), ['Oficina'])

    def test_devices_missing_from_republish_are_kept(self):
        proxy, mqtt, _ = make_proxy()
        mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        self.assertEqual(set(proxy.get_thing_names()), {'Oficina', 'SensorPuertaEntrada'})

    def test_lights_are_monkeypatched(self):
        proxy, mqtt, _ = make_proxy()
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        lamp = proxy.get_thing('Oficina')
        lamp.set_brightness_pct(50)
        lamp.turn_on()
        self.assertTrue(lamp.is_light_on())

    def test_subscribes_to_extras_of_registered_things_only(self):
        _, mqtt, _ = make_proxy(cb_is_device_interesting=lambda t: t.thing_type == 'light')
        mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])
        self.assertIn('zmw_thing_extras/Oficina', mqtt.subscriptions)
        self.assertNotIn('zmw_thing_extras/SensorPuertaEntrada', mqtt.subscriptions)

    def test_extras_updates_reach_thing(self):
        proxy, mqtt, _ = make_proxy()
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        mqtt.subscriptions['zmw_thing_extras/Oficina']('', {'feels_like': 21})
        self.assertEqual(proxy.get_thing('Oficina').extras.get('feels_like'), 21)

    def test_alias(self):
        proxy, mqtt, _ = make_proxy()
        proxy._aliases = {'Oficina': 'OfficeLamp'}
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        self.assertEqual(proxy.get_thing_names(), ['OfficeLamp'])
        lamp = proxy.get_thing('OfficeLamp')
        self.assertEqual(lamp.real_name, 'Oficina')
        self.assertIn('zmw_thing_extras/OfficeLamp', mqtt.subscriptions)


class TestZ2MProxyMessageDispatch(unittest.TestCase):
    def setUp(self):
        self.proxy, self.mqtt, _ = make_proxy()
        self.mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])
        self.lamp = self.proxy.get_thing('Oficina')

    def test_update_by_name(self):
        self.mqtt.deliver('Oficina', {'state': 'ON', 'brightness': 100})
        self.assertEqual(self.lamp.get_json_state()['state'], True)
        self.assertEqual(self.lamp.get_json_state()['brightness'], 100)

    def test_update_by_address(self):
        self.mqtt.deliver(LAMP_ADDR, {'state': 'ON'})
        self.assertEqual(self.lamp.get_json_state()['state'], True)

    def test_update_from_set_echo(self):
        self.mqtt.deliver('Oficina/set', {'brightness': 42})
        self.assertEqual(self.lamp.get_json_state()['brightness'], 42)

    def test_update_only_reaches_target_thing(self):
        sensor = self.proxy.get_thing('SensorPuertaEntrada')
        before = sensor.get_json_state()
        self.mqtt.deliver('Oficina', {'state': 'ON'})
        self.assertEqual(sensor.get_json_state(), before)

    def test_state_change_cb(self):
        changes = []
        self.lamp.on_state_change_from_mqtt = lambda t: changes.append((t.name, t.get('state')))
        self.mqtt.deliver('Oficina', {'state': 'ON'})
        self.assertEqual(changes, [('Oficina', True)])

    def test_unknown_topic_warns(self):
        with self.assertLogs('Z2M', level='WARNING'):
            self.mqtt.deliver('NotAThing', {'state': 'ON'})

    def test_bridge_topics_are_silently_ignored(self):
        for sub in ('bridge/state', 'bridge/extensions', 'bridge/logging', 'bridge/info', 'bridge/config',
                    'bridge/converters', 'bridge/definitions', 'bridge/event',
                    'bridge/response/device/rename', 'bridge/response/health_check'):
            with self.assertNoLogs('Z2M', level='WARNING'):
                self.mqtt.deliver(sub, {})

    def test_uninteresting_device_messages_are_silently_ignored(self):
        proxy, mqtt, _ = make_proxy(cb_is_device_interesting=lambda t: t.thing_type == 'light')
        mqtt.deliver('bridge/devices', [get_a_lamp(), get_motion_sensor()])
        with self.assertNoLogs('Z2M', level='WARNING'):
            mqtt.deliver('MotionSensor1', {'occupancy': True})
            mqtt.deliver('MotionSensor1/set', {})

    def test_group_topics_are_silently_ignored(self):
        # Pins current behaviour: groups are ignored by '<id>/' and '<id>/availability'
        self.mqtt.deliver('bridge/groups', [{'id': 7}])
        with self.assertNoLogs('Z2M', level='WARNING'):
            self.mqtt.deliver('7/', {})
            self.mqtt.deliver('7/availability', {})

    def test_malformed_group_logs_error(self):
        with self.assertLogs('Z2M', level='ERROR'):
            self.mqtt.deliver('bridge/groups', [{'no_id': 7}])

    def test_alias_receives_updates_on_real_name(self):
        proxy, mqtt, _ = make_proxy()
        proxy._aliases = {'Oficina': 'OfficeLamp'}
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        lamp = proxy.get_thing('OfficeLamp')
        mqtt.deliver('Oficina', {'state': 'ON'})
        self.assertEqual(lamp.get_json_state()['state'], True)
        mqtt.deliver('OfficeLamp', {'state': 'OFF'})
        self.assertEqual(lamp.get_json_state()['state'], False)


class TestZ2MProxyBroadcast(unittest.TestCase):
    def setUp(self):
        self.proxy, self.mqtt, _ = make_proxy()
        self.mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])
        self.lamp = self.proxy.get_thing('Oficina')

    def test_broadcast_thing(self):
        self.lamp.set('state', True)
        self.proxy.broadcast_thing(self.lamp)
        self.assertEqual(self.mqtt.broadcasts, [('zigbee2mqtt/Oficina/set', {'state': 'ON'})])

    def test_broadcast_thing_by_name(self):
        self.lamp.set('brightness', 10)
        self.proxy.broadcast_thing('Oficina')
        self.assertEqual(self.mqtt.broadcasts, [('zigbee2mqtt/Oficina/set', {'brightness': 10})])

    def test_broadcast_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            self.proxy.broadcast_thing('NotAThing')

    def test_broadcast_without_changes_is_silent(self):
        self.proxy.broadcast_thing(self.lamp)
        self.assertEqual(self.mqtt.broadcasts, [])

    def test_broadcast_clears_pending_changes(self):
        self.lamp.set('state', True)
        self.proxy.broadcast_thing(self.lamp)
        self.proxy.broadcast_thing(self.lamp)
        self.assertEqual(len(self.mqtt.broadcasts), 1)

    def test_broadcast_extras(self):
        self.lamp.extras.set('foo', 1)
        self.proxy.broadcast_thing(self.lamp)
        self.assertEqual(self.mqtt.broadcasts, [('zmw_thing_extras/Oficina', {'foo': 1})])

    def test_broadcast_values_then_extras(self):
        self.lamp.set('state', False)
        self.lamp.extras.set('foo', 1)
        self.proxy.broadcast_thing(self.lamp)
        self.assertEqual(self.mqtt.broadcasts, [
            ('zigbee2mqtt/Oficina/set', {'state': 'OFF'}),
            ('zmw_thing_extras/Oficina', {'foo': 1}),
        ])

    def test_broadcast_things_mixed_objects_and_names(self):
        sensor = self.proxy.get_thing('SensorPuertaEntrada')
        self.lamp.set('state', True)
        sensor.extras.set('bar', 2)
        self.proxy.broadcast_things([self.lamp, 'SensorPuertaEntrada'])
        self.assertEqual(self.mqtt.broadcasts, [
            ('zigbee2mqtt/Oficina/set', {'state': 'ON'}),
            ('zmw_thing_extras/SensorPuertaEntrada', {'bar': 2}),
        ])

    def test_broadcast_uses_custom_topic(self):
        proxy, mqtt, _ = make_proxy(topic='custom_z2m')
        mqtt.deliver('bridge/devices', [get_a_lamp()], topic='custom_z2m')
        lamp = proxy.get_thing('Oficina')
        lamp.set('state', True)
        proxy.broadcast_thing(lamp)
        self.assertEqual(mqtt.broadcasts, [('custom_z2m/Oficina/set', {'state': 'ON'})])

    def test_broadcast_alias_uses_real_name(self):
        proxy, mqtt, _ = make_proxy()
        proxy._aliases = {'Oficina': 'OfficeLamp'}
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        lamp = proxy.get_thing('OfficeLamp')
        lamp.set('state', True)
        lamp.extras.set('foo', 1)
        proxy.broadcast_thing(lamp)
        self.assertEqual(mqtt.broadcasts, [
            ('zigbee2mqtt/Oficina/set', {'state': 'ON'}),
            ('zmw_thing_extras/OfficeLamp', {'foo': 1}),
        ])


class TestZ2MProxyQueries(unittest.TestCase):
    def setUp(self):
        self.proxy, self.mqtt, _ = make_proxy()
        self.mqtt.deliver('bridge/devices', [get_a_lamp(), get_contact_sensor()])

    def test_get_thing_unknown_raises(self):
        with self.assertRaises(KeyError):
            self.proxy.get_thing('NotAThing')

    def test_get_things_if(self):
        lights = self.proxy.get_things_if(lambda t: t.thing_type == 'light')
        self.assertEqual([t.name for t in lights], ['Oficina'])

    def test_get_all_registered_things(self):
        names = {t.name for t in self.proxy.get_all_registered_things()}
        self.assertEqual(names, {'Oficina', 'SensorPuertaEntrada'})

    def test_get_world_state(self):
        world = self.proxy.get_world_state()
        self.assertEqual(len(world), 2)
        by_name = {k: v for entry in world for k, v in entry.items()}
        self.assertEqual(set(by_name.keys()), {'Oficina', 'SensorPuertaEntrada'})
        self.assertIn('state', by_name['Oficina'])

    def test_get_thing_meta(self):
        meta = self.proxy.get_thing_meta('Oficina')
        self.assertEqual(meta['name'], 'Oficina')
        self.assertEqual(meta['address'], LAMP_ADDR)
        self.assertEqual(meta['thing_type'], 'light')

    def test_get_thing_meta_unknown(self):
        self.assertIsNone(self.proxy.get_thing_meta('NotAThing'))

    def test_known_things_hash(self):
        h1 = self.proxy.get_known_things_hash()
        self.assertIsInstance(h1, str)
        self.assertEqual(h1, self.proxy.get_known_things_hash())
        self.mqtt.deliver('bridge/devices', [get_motion_sensor()])
        self.assertNotEqual(h1, self.proxy.get_known_things_hash())

    def test_known_things_hash_is_order_independent(self):
        other, mqtt, _ = make_proxy()
        mqtt.deliver('bridge/devices', [get_contact_sensor(), get_a_lamp()])
        self.assertEqual(self.proxy.get_known_things_hash(), other.get_known_things_hash())


class TestZ2MProxyVirtualThings(unittest.TestCase):
    def test_register_virtual_thing(self):
        proxy, mqtt, _ = make_proxy()
        proxy.register_virtual_thing(create_virtual_thing('Weather', 'Outside weather', 'sensor', 'SomeApi'))
        self.assertIn('Weather', proxy.get_thing_names())
        self.assertIn('zmw_thing_extras/Weather', mqtt.subscriptions)

    def test_virtual_thing_broadcasts_extras_only(self):
        proxy, mqtt, _ = make_proxy()
        vt = create_virtual_thing('Weather', 'Outside weather', 'sensor', 'SomeApi')
        proxy.register_virtual_thing(vt)
        vt.extras.set('temp', 12)
        proxy.broadcast_thing(vt)
        self.assertEqual(mqtt.broadcasts, [('zmw_thing_extras/Weather', {'temp': 12})])

    def test_duplicate_virtual_thing_is_rejected(self):
        proxy, _, _ = make_proxy()
        first = create_virtual_thing('Weather', 'first', 'sensor', 'SomeApi')
        proxy.register_virtual_thing(first)
        with self.assertLogs('Z2M', level='ERROR'):
            proxy.register_virtual_thing(create_virtual_thing('Weather', 'second', 'sensor', 'SomeApi'))
        self.assertIs(proxy.get_thing('Weather'), first)

    def test_virtual_thing_shadows_network_device_with_same_name(self):
        # Pins current behaviour: first registration wins, network device is dropped (step 8 will make this loud)
        proxy, mqtt, _ = make_proxy()
        vt = create_virtual_thing('Oficina', 'virtual', 'sensor', 'SomeApi')
        proxy.register_virtual_thing(vt)
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        self.assertIs(proxy.get_thing('Oficina'), vt)

    def test_virtual_thing_survives_discovery(self):
        proxy, mqtt, _ = make_proxy()
        proxy.register_virtual_thing(create_virtual_thing('Weather', 'Outside weather', 'sensor', 'SomeApi'))
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        self.assertEqual(set(proxy.get_thing_names()), {'Weather', 'Oficina'})


class TestZ2MProxyHealth(unittest.TestCase):
    def _run_connect_check(self, sched):
        connect_check, _, _ = sched.jobs[0]
        connect_check()

    @patch('zzmw_lib.z2m.z2mproxy.os.kill')
    def test_connect_check_kills_if_no_network(self, kill):
        _, _, sched = make_proxy()
        with self.assertLogs('Z2M', level='CRITICAL'):
            self._run_connect_check(sched)
        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        self.assertEqual(len(sched.jobs), 1)

    @patch('zzmw_lib.z2m.z2mproxy.os.kill')
    def test_connect_check_schedules_health_check(self, kill):
        _, mqtt, sched = make_proxy()
        mqtt.deliver('bridge/devices', [get_a_lamp()])
        self._run_connect_check(sched)
        kill.assert_not_called()
        self.assertEqual(len(sched.jobs), 2)
        _, trigger, kwargs = sched.jobs[1]
        self.assertEqual(trigger, 'interval')
        self.assertEqual(kwargs['minutes'], 5)
        self.assertEqual(kwargs['id'], 'recurring_job')

    @patch('zzmw_lib.z2m.z2mproxy.os.kill')
    def test_connect_check_is_not_fooled_by_other_messages(self, kill):
        _, mqtt, sched = make_proxy()
        mqtt.deliver('bridge/state', {'state': 'online'})
        with self.assertLogs('Z2M', level='CRITICAL'):
            self._run_connect_check(sched)
        kill.assert_called_once()

    def _health_check_at(self, minutes_since_last_msg):
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        with patch('zzmw_lib.z2m.z2mproxy.datetime') as fake_dt:
            fake_dt.now.return_value = t0
            _, mqtt, sched = make_proxy()
            mqtt.deliver('bridge/devices', [get_a_lamp()])
            self._run_connect_check(sched)
            health_check, _, _ = sched.jobs[1]
            fake_dt.now.return_value = t0 + timedelta(minutes=minutes_since_last_msg)
            health_check()

    def test_health_check_quiet_when_recent_msg(self):
        with self.assertNoLogs('Z2M', level='ERROR'):
            self._health_check_at(minutes_since_last_msg=1)

    def test_health_check_complains_when_stale(self):
        with self.assertLogs('Z2M', level='ERROR'):
            self._health_check_at(minutes_since_last_msg=10)


if __name__ == '__main__':
    unittest.main()
