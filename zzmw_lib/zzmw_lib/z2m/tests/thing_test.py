from setup import get_a_lamp
from setup import get_broken_thing
from setup import get_contact_sensor
from setup import get_lamp_multiple_types
from setup import get_lamp_with_composite_action
from setup import get_motion_sensor

import json
import unittest
from zzmw_lib.z2m.thing import parse_from_zigbee2mqtt
from zzmw_lib.z2m.thing import Zigbee2MqttAction
from zzmw_lib.z2m.thing import Zigbee2MqttActionValue


class TestThings(unittest.TestCase):
    def test_lamp(self):
        t = parse_from_zigbee2mqtt(42, get_a_lamp())
        self.assertEqual(t.thing_id, 42)
        self.assertEqual(t.address, '0x847127fffecda276')
        self.assertEqual(t.name, 'Oficina')
        self.assertEqual(t.broken, False)
        self.assertEqual(t.manufacturer, 'IKEA of Sweden')
        self.assertEqual(t.model, 'LED1732G11')
        self.assertEqual(
            t.description,
            "TRADFRI LED bulb E27 1000 lumen, dimmable, white spectrum, opal white")
        self.assertEqual(t.thing_type, 'light')

        expected_actions = {
            'state',
            'brightness',
            'color_temp',
            'color_temp_startup',
            'effect',
            'power_on_behavior',
            'linkquality'}
        self.assertEqual(
            expected_actions.intersection(
                t.actions), expected_actions)

        for a in t.actions:
            self.assertEqual(t.actions[a].name, a)

        self.assertTrue(t.actions['state'].can_set)
        self.assertTrue(t.actions['state'].can_get)
        self.assertTrue(t.actions['effect'].can_set)
        self.assertFalse(t.actions['effect'].can_get)
        self.assertFalse(t.actions['linkquality'].can_set)
        self.assertFalse(t.actions['linkquality'].can_get)

        self.assertEqual(t.actions['state'].value.meta['type'], 'binary')
        self.assertEqual(t.actions['state'].value.meta['value_off'], 'OFF')
        self.assertEqual(t.actions['state'].value.meta['value_on'], 'ON')

        self.assertEqual(t.actions['brightness'].value.meta['type'], 'numeric')
        self.assertEqual(t.actions['brightness'].value.meta['value_min'], 0)
        self.assertEqual(t.actions['brightness'].value.meta['value_max'], 254)

        self.assertEqual(t.actions['effect'].value.meta['type'], 'enum')
        self.assertEqual(len(t.actions['effect'].value.meta['values']), 6)

    def test_sensor(self):
        t = parse_from_zigbee2mqtt(0, get_contact_sensor())
        self.assertEqual(t.address, '0x00158d0008ad5e77')
        self.assertEqual(t.name, 'SensorPuertaEntrada')
        self.assertEqual(t.broken, False)
        self.assertEqual(t.manufacturer, 'LUMI')
        self.assertEqual(t.model, 'MCCGQ11LM')
        self.assertEqual(t.thing_type, None)
        self.assertEqual(len(t.actions), 5)

    def test_alias(self):
        t = parse_from_zigbee2mqtt(0, get_contact_sensor(), known_aliases={'SensorPuertaEntrada': 'AliasName'})
        self.assertEqual(t.address, '0x00158d0008ad5e77')
        self.assertEqual(t.name, 'AliasName')
        self.assertEqual(t.real_name, 'SensorPuertaEntrada')
        self.assertEqual(t.manufacturer, 'LUMI')
        self.assertEqual(t.model, 'MCCGQ11LM')
        self.assertEqual(t.thing_type, None)
        self.assertEqual(len(t.actions), 5)

    def test_debug(self):
        t = parse_from_zigbee2mqtt(0, get_contact_sensor())
        dbg = t.debug_str()
        self.assertTrue('SensorPuertaEntrada' in dbg)
        self.assertTrue('battery' in dbg)
        self.assertTrue('contact' in dbg)
        self.assertTrue('temperature' in dbg)
        self.assertTrue('voltage' in dbg)
        self.assertTrue('linkquality' in dbg)

    def test_dictify(self):
        t = parse_from_zigbee2mqtt(42, get_a_lamp())
        d = t.dictify()
        self.assertEqual(d['thing_id'], 42)
        self.assertEqual(d['address'], '0x847127fffecda276')
        self.assertEqual(d['name'], 'Oficina')
        self.assertEqual(d['real_name'], 'Oficina')
        self.assertEqual(d['broken'], False)
        self.assertEqual(d['manufacturer'], 'IKEA of Sweden')
        self.assertEqual(d['model'], 'LED1732G11')
        self.assertEqual(d['thing_type'], 'light')
        self.assertEqual(d['is_zigbee_mqtt'], True)
        self.assertTrue('actions' in d)
        self.assertTrue('state' in d['actions'])
        self.assertTrue('brightness' in d['actions'])
        self.assertEqual(d['actions']['state']['name'], 'state')
        self.assertEqual(d['actions']['state']['can_set'], True)
        self.assertEqual(d['actions']['state']['can_get'], True)
        self.assertEqual(d['actions']['state']['value']['meta']['type'], 'binary')
        self.assertEqual(d['actions']['brightness']['value']['meta']['type'], 'numeric')

    def test_broken(self):
        t = parse_from_zigbee2mqtt(0, get_broken_thing())
        self.assertTrue(t.broken)
        self.assertEqual(t.address, 'bar')
        self.assertEqual(t.name, 'foo')

    def test_values_are_actions(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        values_names = set(t.get_json_state().keys()) - {'thing_name'}
        actions = set(t.actions)
        self.assertEqual(actions.intersection(values_names), values_names)

    def test_default_values_are_null(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        state = t.get_json_state()
        for k in state.keys():
            if k == 'thing_name':
                continue
            self.assertEqual(state[k], None)
            self.assertEqual(t.get(k), None)

    def test_values_update_from_mqtt(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        t.on_mqtt_update('topic', json.loads(
            '{"brightness":145,"color_mode":"color_temp","color_temp":370,"linkquality":120,"state":"ON","update":{"state":"idle"}}'))
        state = t.get_json_state()
        self.assertEqual(state['state'], True)
        self.assertEqual(t.get('state'), True)
        self.assertEqual(state['brightness'], 145)
        self.assertEqual(t.get('brightness'), 145)
        self.assertEqual(state['color_temp'], 370)
        self.assertEqual(t.get('color_temp'), 370)
        self.assertEqual(state['linkquality'], 120)
        self.assertEqual(t.get('linkquality'), 120)

    def test_partial_values_update_from_mqtt(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        t.on_mqtt_update('topic', json.loads(
            '{"brightness":145,"state":"ON"}'))
        state = t.get_json_state()
        self.assertEqual(state['state'], True)
        self.assertEqual(t.get('state'), True)
        self.assertEqual(state['brightness'], 145)
        self.assertEqual(t.get('brightness'), 145)
        self.assertEqual(state['color_temp'], None)
        self.assertEqual(t.get('color_temp'), None)
        self.assertEqual(state['linkquality'], None)
        self.assertEqual(t.get('linkquality'), None)

        t.on_mqtt_update('topic', json.loads(
            '{"brightness":123,"linkquality":42}'))
        state = t.get_json_state()
        self.assertEqual(state['state'], True)
        self.assertEqual(t.get('state'), True)
        self.assertEqual(state['brightness'], 123)
        self.assertEqual(t.get('brightness'), 123)
        self.assertEqual(state['color_temp'], None)
        self.assertEqual(t.get('color_temp'), None)
        self.assertEqual(state['linkquality'], 42)
        self.assertEqual(t.get('linkquality'), 42)

        t.on_mqtt_update('topic', json.loads(
            '{"state":"OFF","linkquality":111}'))
        state = t.get_json_state()
        self.assertEqual(state['state'], False)
        self.assertEqual(t.get('state'), False)
        self.assertEqual(state['brightness'], 123)
        self.assertEqual(t.get('brightness'), 123)
        self.assertEqual(state['color_temp'], None)
        self.assertEqual(t.get('color_temp'), None)
        self.assertEqual(state['linkquality'], 111)
        self.assertEqual(t.get('linkquality'), 111)

    def test_rejects_invalid_values_from_mqtt(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        t.on_mqtt_update('topic', json.loads(
            '{"brightness":145,"state":"ON","effect":"blink"}'))
        state = t.get_json_state()
        self.assertEqual(state['state'], True)
        self.assertEqual(state['brightness'], 145)
        self.assertEqual(state['effect'], 'blink')

        t.on_mqtt_update('topic', json.loads(
            '{"brightness":5321,"state":"FOO","effect":"BAR"}'))
        state = t.get_json_state()
        self.assertEqual(state['state'], True)
        self.assertEqual(state['brightness'], 145)
        self.assertEqual(state['effect'], 'blink')

    def test_update_from_mqtt_triggers_cb(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())

        localCalled = False

        def cb(v):
            nonlocal localCalled
            localCalled = True
            self.assertEqual(v, 145)

        globalCalled = False

        def global_cb(_thing):
            nonlocal globalCalled
            globalCalled = True

        t.on_any_change_from_mqtt = global_cb
        t.actions['brightness'].value.on_change_from_mqtt = cb
        t.on_mqtt_update('topic', json.loads('{"brightness":145}'))
        self.assertEqual(t.get('brightness'), 145)
        self.assertTrue(localCalled)
        self.assertTrue(globalCalled)

    def test_update_from_mqtt_triggers_multiple_cbs(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())

        calledB = False

        def cbB(v):
            nonlocal calledB
            calledB = True

        calledS = False

        def cbS(v):
            nonlocal calledS
            calledS = True

        globalCalled = 0

        def global_cb(_thing):
            nonlocal globalCalled
            globalCalled += 1

        t.on_any_change_from_mqtt = global_cb
        t.actions['brightness'].value.on_change_from_mqtt = cbB
        t.actions['state'].value.on_change_from_mqtt = cbS
        t.on_mqtt_update('topic', json.loads('{"brightness":145}'))
        self.assertEqual(t.get('brightness'), 145)
        self.assertTrue(calledB)
        self.assertFalse(calledS)
        self.assertEqual(globalCalled, 1)

        calledB = False
        t.on_mqtt_update('topic', json.loads(
            '{"brightness":111, "state": false}'))
        self.assertTrue(calledB)
        self.assertTrue(calledS)
        self.assertEqual(globalCalled, 2)

    def test_update_from_mqtt_triggers_correct_cb(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())

        called = False

        def cb(_):
            nonlocal called
            called = True

        t.actions['state'].value.on_change_from_mqtt = cb
        t.on_mqtt_update('topic', json.loads('{"brightness":145}'))
        self.assertEqual(t.get('brightness'), 145)
        self.assertFalse(called)

    def test_accepts_user_values(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        t.set('state', True)
        t.set('brightness', 123)
        t.set('effect', 'blink')
        state = t.get_json_state()
        self.assertEqual(state['state'], True)
        self.assertEqual(state['brightness'], 123)
        self.assertEqual(state['effect'], 'blink')

    def test_binary_values_update_from_user(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        t.set('state', True)
        self.assertEqual(t.get('state'), True)
        t.set('state', False)
        self.assertEqual(t.get('state'), False)
        t.set('state', '1')
        self.assertEqual(t.get('state'), True)
        t.set('state', '0')
        self.assertEqual(t.get('state'), False)
        t.set('state', 'True')
        self.assertEqual(t.get('state'), True)
        t.set('state', 'False')
        self.assertEqual(t.get('state'), False)
        t.set('state', 'TrUE')
        self.assertEqual(t.get('state'), True)
        t.set('state', 'FaLSe')
        self.assertEqual(t.get('state'), False)

    def test_update_from_user_triggers_no_cb(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())

        called = False

        def cb(_):
            nonlocal called
            called = True

        t.actions['state'].value.on_change_from_mqtt = cb
        t.set('brightness', 123)
        self.assertEqual(t.get('brightness'), 123)
        self.assertFalse(called)

    def test_get_rejects_nonexistant_action(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        with self.assertRaises(AttributeError):
            t.get('foo')

    def test_rejects_ro_user_values(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        with self.assertRaises(ValueError):
            t.set('linkquality', 123)

    def test_rejects_invalid_user_values(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        with self.assertRaises(ValueError):
            t.set('brightness', 12345)
        with self.assertRaises(ValueError):
            t.set('effect', 'FOO')

    def test_propagates_user_changes(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())

        # Nothing to propagate by default
        self.assertEqual(t.make_mqtt_status_update(), {})

        # Local state change
        t.set('state', True)
        self.assertEqual(t.make_mqtt_status_update(), {'state': 'ON'})
        self.assertEqual(t.get_json_state()['state'], True)

        # Change now propagated
        self.assertEqual(t.make_mqtt_status_update(), {})

        # Propagates multiple changes
        # (NB: there's no check of actual value change, only of user setting a value)
        t.set('state', False)
        t.set('brightness', 123)
        self.assertEqual(
            t.make_mqtt_status_update(), {
                'state': 'OFF', 'brightness': 123})
        self.assertEqual(t.make_mqtt_status_update(), {})
        self.assertEqual(t.get_json_state()['state'], False)
        self.assertEqual(t.get_json_state()['brightness'], 123)

    def test_doesnt_propagate_mqtt_changes(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        self.assertEqual(t.get_json_state()['state'], None)
        t.on_mqtt_update('topic', json.loads(
            '{"state":"OFF","linkquality":111}'))
        self.assertEqual(t.make_mqtt_status_update(), {})
        self.assertEqual(t.get_json_state()['state'], False)

    def test_propagates_user_change_after_mqtt_change(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        self.assertEqual(t.get_json_state()['state'], None)
        self.assertEqual(t.get_json_state()['brightness'], None)

        t.on_mqtt_update('topic', json.loads(
            '{"state":"OFF","linkquality":111}'))
        self.assertEqual(t.get_json_state()['state'], False)
        self.assertEqual(t.get_json_state()['brightness'], None)
        self.assertEqual(t.make_mqtt_status_update(), {})

        t.set('state', False)
        t.set('brightness', 123)
        self.assertEqual(t.get_json_state()['state'], False)
        self.assertEqual(t.get_json_state()['brightness'], 123)
        self.assertEqual(
            t.make_mqtt_status_update(), {
                'state': 'OFF', 'brightness': 123})
        self.assertEqual(t.make_mqtt_status_update(), {})
        self.assertEqual(t.get_json_state()['state'], False)
        self.assertEqual(t.get_json_state()['brightness'], 123)

    def test_user_change_wins_over_mqtt_change(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        t.set('brightness', 200)
        t.on_mqtt_update('topic', json.loads('{"brightness":100}'))
        self.assertEqual(t.make_mqtt_status_update(), {'brightness': 200})
        self.assertEqual(t.get_json_state()['brightness'], 200)

    def test_lamp_presets(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        self.assertTrue('presets' in t.actions['color_temp'].value.meta)
        found = set(p['name']
                    for p in t.actions['color_temp'].value.meta['presets'])
        expect = set({'coolest', 'cool', 'neutral', 'warm', 'warmest'})
        self.assertEqual(found.intersection(expect), expect)

    def test_lamp_presets_debug_str(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        dbg = t.debug_str()
        for name in ['coolest', 'cool', 'neutral', 'warm', 'warmest']:
            self.assertTrue(name in dbg)

    def test_lamp_preset_value_from_user(self):
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        self.assertEqual(t.get_json_state()['color_temp'], None)
        t.set('color_temp', 'warm')
        self.assertEqual(t.get_json_state()['color_temp'], 454)
        self.assertEqual(t.make_mqtt_status_update(), {'color_temp': 454})

    def test_lamp_preset_value_from_mqtt(self):
        # Don't think this should happen, but if it does...
        t = parse_from_zigbee2mqtt(0, get_a_lamp())
        t.on_mqtt_update('topic', json.loads('{"color_temp":"warm"}'))
        self.assertEqual(t.get_json_state()['color_temp'], 454)
        self.assertEqual(t.make_mqtt_status_update(), {})
        t.set('color_temp', 'cool')
        self.assertEqual(t.make_mqtt_status_update(), {'color_temp': 250})
        self.assertEqual(t.get_json_state()['color_temp'], 250)

    def test_motion_sensor(self):
        t = parse_from_zigbee2mqtt(0, get_motion_sensor())
        t.on_mqtt_update('ignored', json.loads(
            '{"battery":74,"illuminance_above_threshold":false,"linkquality":65,"occupancy":false,"update":{"state":"idle"}}'))
        self.assertEqual(t.get_json_state()['battery'], 74)
        self.assertEqual(
            t.get_json_state()['illuminance_above_threshold'], False)
        self.assertEqual(t.get_json_state()['occupancy'], False)
        self.assertEqual(t.get_json_state()['linkquality'], 65)

    def test_composite_action_parses_ok(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        self.assertEqual(t.actions['color_hs'].name, 'color_hs')
        self.assertEqual(t.actions['color_hs'].value.meta['type'], 'composite')
        self.assertEqual(
            len(t.actions['color_hs'].value.meta['composite_actions']), 2)
        self.assertEqual(
            t.actions['color_hs'].value.meta['composite_actions']['hue'].value.meta['type'],
            'numeric')
        self.assertEqual(
            t.actions['color_hs'].value.meta['composite_actions']['saturation'].value.meta['type'],
            'numeric')
        self.assertEqual(t.actions['color_hs'].value.meta['property'], 'color')
        self.assertEqual(t.actions['color_xy'].name, 'color_xy')
        self.assertEqual(t.actions['color_xy'].value.meta['type'], 'composite')
        self.assertEqual(t.actions['color_xy'].value.meta['property'], 'color')
        self.assertEqual(
            len(t.actions['color_xy'].value.meta['composite_actions']), 2)
        self.assertEqual(
            t.actions['color_xy'].value.meta['composite_actions']['x'].value.meta['type'],
            'numeric')
        self.assertEqual(
            t.actions['color_xy'].value.meta['composite_actions']['y'].value.meta['type'],
            'numeric')

    def test_composite_action_updates_from_mqtt(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        t.on_mqtt_update('topic', json.loads(
            '{"state":"OFF","color":{"x":0.123,"y":0.456},"color_mode":"xy"}'))
        self.assertEqual(
            t.actions['color_xy'].value.get_value(), {
                'x': 0.123, 'y': 0.456})
        self.assertEqual(t.get_json_state()['color'], {'x': 0.123, 'y': 0.456})
        self.assertEqual(t.get_json_state()['state'], False)

    def test_partial_composite_update_creates_dynamic_action(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        t.on_mqtt_update('topic', json.loads(
            '{"state":"ON","color":{"x":0.123}}'))
        # Composite action rejects partial update
        self.assertEqual(t.actions['color_xy'].value.get_value(), None)
        # But a dynamic user-defined action is created for the unknown field
        self.assertTrue('color' in t.actions)
        self.assertEqual(t.actions['color'].value.meta['type'], 'user_defined')
        self.assertEqual(t.get('color'), {'x': 0.123})
        self.assertEqual(t.get_json_state()['state'], True)

    def test_composite_action_updates_from_user(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        t.actions['color_xy'].set_value({'x': 0.123, 'y': 0.456})
        self.assertEqual(
            t.actions['color_xy'].value.get_value(), {
                'x': 0.123, 'y': 0.456})
        self.assertEqual(t.get_json_state()['color'], {'x': 0.123, 'y': 0.456})

    def test_composite_action_updates_from_user_as_string(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        t.actions["color_xy"].set_value('{"x": 0.123, "y": 0.456}')
        self.assertEqual(
            t.actions['color_xy'].value.get_value(), {
                'x': 0.123, 'y': 0.456})
        self.assertEqual(t.get_json_state()['color'], {'x': 0.123, 'y': 0.456})

    def test_composite_action_rejects_partial_update_from_user(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        t.actions['color_xy'].set_value({'x': 0.123})
        self.assertEqual(t.actions['color_xy'].value.get_value(), None)
        self.assertTrue('color' not in t.get_json_state())

    def test_composite_action_broadcasts_to_mqtt_after_user_update(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())

        self.assertEqual(t.actions['color_xy'].value.get_value(), None)
        self.assertTrue('color' not in t.get_json_state())
        self.assertEqual(t.make_mqtt_status_update(), {})

        t.on_mqtt_update('topic', json.loads(
            '{"state":"OFF","color":{"x":0.123,"y":0.456},"color_mode":"xy"}'))
        self.assertEqual(
            t.actions['color_xy'].value.get_value(), {
                'x': 0.123, 'y': 0.456})
        self.assertEqual(t.get_json_state()['color'], {'x': 0.123, 'y': 0.456})
        self.assertEqual(t.get_json_state()['state'], False)
        self.assertEqual(t.make_mqtt_status_update(), {})

        t.actions['color_xy'].set_value({'x': 0.789, 'y': 0.987})
        self.assertEqual(
            t.actions['color_xy'].value.get_value(), {
                'x': 0.789, 'y': 0.987})
        self.assertEqual(t.get_json_state()['color'], {'x': 0.789, 'y': 0.987})
        self.assertEqual(
            t.make_mqtt_status_update(), {
                'color': {
                    'x': 0.789, 'y': 0.987}})
        self.assertEqual(t.make_mqtt_status_update(), {})

        t.actions['color_xy'].set_value({'x': 0.123, 'y': 0.456})
        t.actions['state'].set_value(True)
        self.assertEqual(
            t.make_mqtt_status_update(), {
                'color': {
                    'x': 0.123, 'y': 0.456}, 'state': 'ON'})

    def test_composite_action_debug_str(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        self.assertTrue('hue' in t.debug_str())
        self.assertTrue('saturation' in t.debug_str())

    def test_ignored_action_for_unknown_composite_field(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        # Send a composite update with an unknown field 'z'
        t.on_mqtt_update('topic', json.loads(
            '{"color":{"x":0.1,"y":0.2,"z":0.3}}'))
        # The composite value should remain None (update rejected)
        self.assertEqual(t.actions['color_xy'].value.get_value(), None)
        # An IgnoredAction should be created for the unknown field
        self.assertTrue('z' in t.actions['color_xy'].value.meta['composite_actions'])
        ignored = t.actions['color_xy'].value.meta['composite_actions']['z']
        self.assertEqual(ignored.name, 'z')
        self.assertEqual(ignored.debug_str(), 'z=IGNORED')
        self.assertEqual(ignored.dictify(), 'z=IGNORED')
        self.assertEqual(ignored.value.debug_str(), 'IGNORED')
        # Subsequent updates with the ignored field should also be silently ignored
        t.on_mqtt_update('topic', json.loads(
            '{"color":{"x":0.5,"y":0.5,"z":0.9}}'))
        self.assertEqual(t.actions['color_xy'].value.get_value(), None)

    def test_multiple_ignored_actions_for_unknown_composite_fields(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())
        # First update adds 'z' as IgnoredAction
        t.on_mqtt_update('topic', json.loads(
            '{"color":{"x":0.1,"y":0.2,"z":0.3}}'))
        self.assertTrue('z' in t.actions['color_xy'].value.meta['composite_actions'])
        # Second update adds 'w' as IgnoredAction
        t.on_mqtt_update('topic', json.loads(
            '{"color":{"x":0.1,"y":0.2,"w":0.4}}'))
        self.assertTrue('w' in t.actions['color_xy'].value.meta['composite_actions'])
        # Both should be IgnoredActions
        ignored_z = t.actions['color_xy'].value.meta['composite_actions']['z']
        ignored_w = t.actions['color_xy'].value.meta['composite_actions']['w']
        self.assertEqual(ignored_z.debug_str(), 'z=IGNORED')
        self.assertEqual(ignored_w.debug_str(), 'w=IGNORED')
        # Composite value should still be None
        self.assertEqual(t.actions['color_xy'].value.get_value(), None)

    def test_user_defined_action(self):
        t = parse_from_zigbee2mqtt(0, get_lamp_with_composite_action())

        set_called = False

        def cb_on_set(v):
            nonlocal set_called
            set_called = True
            self.assertEqual(v, 42)
        get_called = False

        def cb_on_get():
            nonlocal get_called
            get_called = True
            return 123
        t.actions['foo'] = Zigbee2MqttAction(
            name='foo',
            description='Foo this thing',
            can_set=True,
            can_get=False,
            value=Zigbee2MqttActionValue(
                thing_name=t.name,
                meta={
                    'type': 'user_defined',
                    'on_set': cb_on_set,
                    'on_get': cb_on_get},
                _current=None,
            ))

        t.set('foo', 42)
        self.assertEqual(t.get('foo'), 123)
        self.assertTrue(set_called)
        self.assertTrue(get_called)

    def test_multiple_types(self):
        t = parse_from_zigbee2mqtt(42, get_lamp_multiple_types())
        self.assertEqual(t.thing_type, 'first_thing_type')


if __name__ == '__main__':
    unittest.main()
