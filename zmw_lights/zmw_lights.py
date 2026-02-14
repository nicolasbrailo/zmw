""" Expose a set of lights form zigbee2mqtt over a rest endpoint """
import json
import os
import pathlib
import re

from flask_sock import Sock
from simple_websocket import ConnectionClosed

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner

from zz2m.z2mproxy import Z2MProxy
from zz2m.www import Z2Mwebservice

log = build_logger("ZmwLights")

_Z2M_SKIP_ACTIONS = {
    'linkquality', 'update',
    'identify', 'battery', 'power_on_behavior', 'color_temp_startup',
    'effect', 'execute_if_off',
}

_CAMEL_SPLIT_RE = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')

def _discover_groups(names):
    """Find light groups by CamelCase prefix overlap."""
    # Build valid CamelCase prefixes for each name
    name_prefixes = {}
    for name in names:
        parts = _CAMEL_SPLIT_RE.split(name)
        prefixes = set()
        for i in range(1, len(parts)):
            p = ''.join(parts[:i])
            if len(p) >= 3:
                prefixes.add(p)
        name_prefixes[name] = prefixes

    # Count how many names share each prefix
    prefix_counts = {}
    for prefixes in name_prefixes.values():
        for p in prefixes:
            prefix_counts[p] = prefix_counts.get(p, 0) + 1

    # Assign each name to the prefix with the most members (broadest group)
    groups = {}
    for name, prefixes in name_prefixes.items():
        best = None
        best_count = 1
        for p in prefixes:
            if prefix_counts[p] > best_count:
                best = p
                best_count = prefix_counts[p]
        if best:
            groups.setdefault(best, []).append(name)

    return sorted(
        [{'name': k, 'lights': sorted(v)} for k, v in groups.items()],
        key=lambda g: g['name']
    )

def _describe_action(action):
    """Format a single action as {name, values}, or None to skip."""
    if action.name in _Z2M_SKIP_ACTIONS:
        return None
    meta = action.value.meta
    if meta['type'] in ('composite', 'list', 'user_defined'):
        return None
    if meta['type'] == 'binary':
        return {'name': action.name, 'values': [meta['value_on'], meta['value_off']]}
    if meta['type'] == 'numeric':
        lo = meta.get('value_min', '')
        hi = meta.get('value_max', '')
        if lo != '' or hi != '':
            return {'name': action.name, 'values': [f"{lo}-{hi}"]}
        return {'name': action.name, 'values': []}
    if meta['type'] == 'enum':
        return {'name': action.name, 'values': list(meta.get('values', []))}
    return {'name': action.name, 'values': []}

def _describe_things(things, only_actions=None):
    """Build a list of {name, actions} dicts for a set of Z2M things.
    If only_actions is set, only include actions whose name is in that set."""
    result = []
    for thing in things:
        actions = [a for a in (_describe_action(act) for act in thing.actions.values())
                   if a is not None and (only_actions is None or a['name'] in only_actions)]
        result.append({'name': thing.name, 'actions': actions})
    return result

class ZmwLights(ZmwMqttService):
    """ ZmwService for REST lights """
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_lights", scheduler=sched)
        self._lights = []
        self._switches = []
        self._ws_clients = set()

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.register_www_dir(www_path)
        www.serve_url('/all_lights_on/prefix/<prefix>', self._all_lights_on, methods=['PUT'])
        www.serve_url('/all_lights_off/prefix/<prefix>', self._all_lights_off, methods=['PUT'])
        www.serve_url('/get_lights', lambda: [l.get_json_state() for l in self._lights])
        www.serve_url('/get_switches', lambda: [s.get_json_state() for s in self._switches])
        www.serve_url('/get_groups', self._get_groups)
        www.serve_url('/get_ws_url', lambda: {'url': www.public_url_base.replace('http', 'ws', 1) + '/ws/thing_updates'})

        self._sock = Sock(www)
        self._sock.route('/ws/thing_updates')(self._ws_thing_updates)

        self._z2m = Z2MProxy(cfg, self, sched,
                             cb_on_z2m_network_discovery=self._on_z2m_network_discovery,
                             cb_is_device_interesting=lambda t: t.thing_type in ('light', 'switch'))
        self._z2mw = Z2Mwebservice(www, self._z2m)


    def _on_z2m_network_discovery(self, is_first_discovery, known_things):
        all_things = self._z2m.get_all_registered_things()
        new_lights = [t for t in all_things if t.thing_type == 'light']
        new_switches = [t for t in all_things if t.thing_type == 'switch']

        log.info("Z2M network discovered, there are %d lights and %d switches",
                 len(new_lights), len(new_switches))

        old_light_names = {light.name for light in self._lights}
        new_light_names = {light.name for light in new_lights}
        old_switch_names = {switch.name for switch in self._switches}
        new_switch_names = {switch.name for switch in new_switches}

        if not is_first_discovery:
            if old_light_names != new_light_names:
                added = new_light_names - old_light_names
                removed = old_light_names - new_light_names
                if added:
                    log.warning("New lights discovered: %s", ', '.join(added))
                if removed:
                    log.warning("Lights no longer available: %s", ', '.join(removed))
            if old_switch_names != new_switch_names:
                added = new_switch_names - old_switch_names
                removed = old_switch_names - new_switch_names
                if added:
                    log.warning("New switches discovered: %s", ', '.join(added))
                if removed:
                    log.warning("Switches no longer available: %s", ', '.join(removed))

        self._lights = new_lights
        self._switches = new_switches

        for thing in self._lights + self._switches:
            thing.on_state_change_from_mqtt = lambda t=thing: self._on_thing_state_changed(t)

        for light in self._lights:
            log.info("Discovered light %s", light.name)
        for switch in self._switches:
            log.info("Discovered switch %s", switch.name)

    def _ws_thing_updates(self, ws):
        self._ws_clients.add(ws)
        try:
            while True:
                ws.receive()
        except ConnectionClosed:
            pass
        finally:
            self._ws_clients.discard(ws)

    def _on_thing_state_changed(self, thing):
        if not self._ws_clients:
            return
        msg = json.dumps(thing.get_json_state())
        dead = set()
        for ws in self._ws_clients:
            try:
                ws.send(msg)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead

    def _get_groups(self):
        all_names = [t.name for t in self._lights] + [t.name for t in self._switches]
        groups = _discover_groups(all_names)
        assigned = set()
        for g in groups:
            assigned.update(g['lights'])
        others = sorted(set(all_names) - assigned)
        if others:
            groups.append({'name': 'Others', 'lights': others})
        return groups

    def _all_lights_on(self, prefix):
        ls = self._z2m.get_things_if(lambda t: t.thing_type == 'light' and t.name.startswith(prefix))
        for l in ls:
            l.set_brightness_pct(80)
            l.turn_on()
        self._z2m.broadcast_things(ls)
        return {}

    def _all_lights_off(self, prefix):
        ls = self._z2m.get_things_if(lambda t: t.thing_type == 'light' and t.name.startswith(prefix))
        for l in ls:
            l.turn_off()
        self._z2m.broadcast_things(ls)
        return {}

    def get_mqtt_description(self):
        return {
            "description": "Zigbee light/switch control service. Discovers all light and switch devices, groups them by prefix. Provides on/off and brightness controls.",
            "meta": self.get_service_meta(),
            "commands": {
                "get_lights": {
                    "description": "State of all lights. Response on get_lights_reply",
                    "params": {}
                },
                "get_switches": {
                    "description": "State of all switches. Response on get_switches_reply",
                    "params": {}
                },
                "all_lights_on": {
                    "description": "Turn on all lights matching a name prefix at 80% brightness. Response on all_lights_on_reply",
                    "params": {"prefix?": "Prefix to filter lights (eg 'TVRoom')"}
                },
                "all_lights_off": {
                    "description": "Turn off all lights matching a name prefix. Response on all_lights_off_reply",
                    "params": {"prefix?": "Prefix to filter lights (eg 'TVRoom')"}
                },
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "get_lights_reply": {
                    "description": "Array of light state objects",
                    "payload": [{"name": "Light", "state": "ON/OFF", "brightness": "0-255", "...": "other device-specific fields"}]
                },
                "get_switches_reply": {
                    "description": "Array of switch state objects",
                    "payload": [{"name": "Switch", "state": "ON/OFF"}]
                },
                "all_lights_on_reply": {
                    "description": "all_lights_on completed",
                    "payload": {"status": "ok"}
                },
                "all_lights_off_reply": {
                    "description": "all_lights_off completed",
                    "payload": {"status": "ok"}
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {"commands": {}, "announcements": {}}
                },
            },
            "known_lights": _describe_things(self._lights),
            "known_switches": _describe_things(self._switches, only_actions={'state'}),
            "known_groups": _discover_groups([l.name for l in self._lights]),
        }

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "get_lights":
                self.publish_own_svc_message("get_lights_reply",
                    [l.get_json_state() for l in self._lights])
            case "get_switches":
                self.publish_own_svc_message("get_switches_reply",
                    [s.get_json_state() for s in self._switches])
            case "all_lights_on":
                prefix = payload.get('prefix', '')
                self._all_lights_on(prefix)
                self.publish_own_svc_message("all_lights_on_reply", {"status": "ok"})
            case "all_lights_off":
                prefix = payload.get('prefix', '')
                self._all_lights_off(prefix)
                self.publish_own_svc_message("all_lights_off_reply", {"status": "ok"})
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                # Ignore echo
                pass

service_runner(ZmwLights)
