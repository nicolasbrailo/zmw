from z2m_fixtures import get_a_lamp

import unittest

from zzmw_lib.z2m.thing import parse_from_zigbee2mqtt
from zzmw_lib.z2m.light_helpers import (
    any_light_on,
    light_group_toggle_brightness_pct,
    monkeypatch_lights,
    toggle_ensure_color,
    turn_all_lights_off,
)


class FakeZ2M:
    """ The subset of Z2MProxy that light_helpers uses. Records what gets broadcast. """
    def __init__(self, lamp_names):
        self.things = {}
        for i, name in enumerate(lamp_names):
            lamp = get_a_lamp()
            lamp['friendly_name'] = name
            lamp['ieee_address'] = f'0x{i:016x}'
            self.things[name] = parse_from_zigbee2mqtt(i, lamp, 'zigbee2mqtt')
        monkeypatch_lights(self)
        self.broadcasts = []

    def get_thing(self, name):
        return self.things[name]

    def get_things_if(self, cb):
        return [t for t in self.things.values() if cb(t)]

    def broadcast_things(self, things_or_names):
        for t in things_or_names:
            thing = self.things[t] if isinstance(t, str) else t
            update = thing.make_mqtt_status_update()
            if update:
                self.broadcasts.append((thing.name, update))


class TestLightHelpersAvailability(unittest.TestCase):
    """ Unavailable lights keep the last state they reported, which may be stale: helpers must not act on it """
    def setUp(self):
        self.z2m = FakeZ2M(['LampA', 'LampB', 'LampC'])
        self.a = self.z2m.get_thing('LampA')
        self.b = self.z2m.get_thing('LampB')
        self.c = self.z2m.get_thing('LampC')

    def _report(self, lamp, state):
        lamp.on_mqtt_update(lamp.name, {'state': 'ON' if state else 'OFF'})

    def test_any_light_on(self):
        self._report(self.a, True)
        self._report(self.b, False)
        self.assertTrue(any_light_on(self.z2m, ['LampA', 'LampB']))

    def test_any_light_on_ignores_unavailable_lights(self):
        self._report(self.a, True)
        self._report(self.b, False)
        self.a.on_availability_update(False)
        self.assertFalse(any_light_on(self.z2m, ['LampA', 'LampB']))

    def test_group_toggle_turns_on_when_only_unavailable_lights_are_on(self):
        self._report(self.a, True)
        self._report(self.b, False)
        self.a.on_availability_update(False)
        turned_on = light_group_toggle_brightness_pct(self.z2m, [('LampA', 100), ('LampB', 100)])
        self.assertTrue(turned_on)
        self.assertEqual([name for name, _ in self.z2m.broadcasts], ['LampB'])
        # Turning on is done by setting the brightness
        self.assertEqual(self.z2m.broadcasts[0][1], {'brightness': 254})

    def test_group_toggle_leaves_unavailable_lights_untouched(self):
        self._report(self.a, True)
        self._report(self.b, True)
        self.a.on_availability_update(False)
        turned_on = light_group_toggle_brightness_pct(self.z2m, [('LampA', 100), ('LampB', 100)])
        self.assertFalse(turned_on)
        self.assertEqual([name for name, _ in self.z2m.broadcasts], ['LampB'])
        # No pending change left on the unavailable lamp, and its (stale) state is kept
        self.assertEqual(self.a.make_mqtt_status_update(), {})
        self.assertTrue(self.a.is_light_on())

    def test_group_toggle_with_no_available_lights(self):
        self.a.on_availability_update(False)
        self.b.on_availability_update(False)
        self.assertIsNone(light_group_toggle_brightness_pct(self.z2m, [('LampA', 100), ('LampB', 100)]))
        self.assertEqual(self.z2m.broadcasts, [])

    def test_turn_all_lights_off_skips_unavailable_lights(self):
        for lamp in (self.a, self.b, self.c):
            self._report(lamp, True)
        self.b.on_availability_update(False)
        turn_all_lights_off(self.z2m)
        self.assertEqual(sorted(name for name, _ in self.z2m.broadcasts), ['LampA', 'LampC'])
        self.assertEqual(self.b.make_mqtt_status_update(), {})

    def test_toggle_ensure_color_leaves_unavailable_lamp_untouched(self):
        self._report(self.a, True)
        self.a.on_availability_update(False)
        self.assertFalse(toggle_ensure_color(self.a, 'FFA9A9'))
        self.assertEqual(self.a.make_mqtt_status_update(), {})


if __name__ == '__main__':
    unittest.main()
