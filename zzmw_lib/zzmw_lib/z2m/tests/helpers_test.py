from setup import get_a_lamp

import json
import unittest
from zzmw_lib.z2m.thing import parse_from_zigbee2mqtt
from zzmw_lib.z2m.helpers import bind_callbacks_to_z2m_actions


class TestBindCallbacks(unittest.TestCase):
    def test_bind_callbacks_to_thing_actions(self):
        # Create a lamp thing
        lamp = parse_from_zigbee2mqtt(1, get_a_lamp())
        known_things = {'Oficina': lamp}

        # Create an object with callback methods
        class CallbackHolder:
            def __init__(self):
                self.brightness_called = False
                self.brightness_value = None
                self.state_called = False
                self.state_value = None

            def z2m_cb_Oficina_brightness(self, val):
                self.brightness_called = True
                self.brightness_value = val

            def z2m_cb_Oficina_state(self, val):
                self.state_called = True
                self.state_value = val

            def z2m_cb_NonExistent_action(self, val):
                pass  # This should remain unbound

        holder = CallbackHolder()
        unbound, bound = bind_callbacks_to_z2m_actions(holder, 'z2m_cb_', known_things)

        # Verify return values
        self.assertEqual(set(bound), {'Oficina_brightness', 'Oficina_state'})
        self.assertEqual(set(unbound), {'NonExistent_action'})

        # Verify callbacks are actually bound by triggering MQTT updates
        lamp.on_mqtt_update('topic', json.loads('{"brightness": 200}'))
        self.assertTrue(holder.brightness_called)
        self.assertEqual(holder.brightness_value, 200)
        self.assertFalse(holder.state_called)

        lamp.on_mqtt_update('topic', json.loads('{"state": "ON"}'))
        self.assertTrue(holder.state_called)
        # Callback receives raw MQTT value, not converted boolean
        self.assertEqual(holder.state_value, 'ON')

    def test_bind_callback_to_whole_thing(self):
        lamp = parse_from_zigbee2mqtt(1, get_a_lamp())
        known_things = {'Oficina': lamp}

        class CallbackHolder:
            def __init__(self):
                self.thing_called = False
                self.thing_ref = None

            def z2m_cb_Oficina(self, thing):
                self.thing_called = True
                self.thing_ref = thing

        holder = CallbackHolder()
        unbound, bound = bind_callbacks_to_z2m_actions(holder, 'z2m_cb_', known_things)

        self.assertEqual(bound, ['Oficina'])
        self.assertEqual(unbound, [])

        # Verify callback is bound to on_any_change_from_mqtt
        lamp.on_mqtt_update('topic', json.loads('{"brightness": 150}'))
        self.assertTrue(holder.thing_called)
        self.assertEqual(holder.thing_ref, lamp)

    def test_bind_with_global_pre_callback(self):
        lamp = parse_from_zigbee2mqtt(1, get_a_lamp())
        known_things = {'Oficina': lamp}

        pre_cb_calls = []

        def global_pre_cb(thing_name, action, *args, **kwargs):
            pre_cb_calls.append((thing_name, action, args))

        class CallbackHolder:
            def __init__(self):
                self.called = False

            def z2m_cb_Oficina_brightness(self, val):
                self.called = True

        holder = CallbackHolder()
        unbound, bound = bind_callbacks_to_z2m_actions(
            holder, 'z2m_cb_', known_things, global_pre_cb=global_pre_cb)

        self.assertEqual(bound, ['Oficina_brightness'])

        lamp.on_mqtt_update('topic', json.loads('{"brightness": 100}'))
        self.assertTrue(holder.called)
        self.assertEqual(len(pre_cb_calls), 1)
        self.assertEqual(pre_cb_calls[0][0], 'Oficina')
        self.assertEqual(pre_cb_calls[0][1], 'brightness')


if __name__ == '__main__':
    unittest.main()
