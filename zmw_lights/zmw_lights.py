""" Expose a set of lights form zigbee2mqtt over a rest endpoint """
import json
import os
import pathlib

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.service_runner import service_runner

from zz2m.z2mproxy import Z2MProxy
from zz2m.www import Z2Mwebservice

log = build_logger("ZmwLights")

class ZmwLights(ZmwMqttService):
    """ ZmwService for REST lights """
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_lights", scheduler=sched)
        self._lights = []
        self._switches = []

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        www.register_www_dir(www_path)
        www.serve_url('/all_lights_on/prefix/<prefix>', self._all_lights_on, methods=['PUT'])
        www.serve_url('/all_lights_off/prefix/<prefix>', self._all_lights_off, methods=['PUT'])
        www.serve_url('/get_lights', lambda: [l.get_json_state() for l in self._lights])
        www.serve_url('/get_switches', lambda: [s.get_json_state() for s in self._switches])

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

        for light in self._lights:
            log.info("Discovered light %s", light.name)
        for switch in self._switches:
            log.info("Discovered switch %s", switch.name)

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
            "commands": {
                "get_lights": {
                    "description": "Request state of all discovered lights. Response published on get_lights_reply",
                    "params": {}
                },
                "get_switches": {
                    "description": "Request state of all discovered switches. Response published on get_switches_reply",
                    "params": {}
                },
                "all_lights_on": {
                    "description": "Turn on all lights matching a name prefix at 80% brightness. Response published on all_lights_on_reply",
                    "params": {"prefix": "Name prefix to filter lights (e.g. 'TVRoom')"}
                },
                "all_lights_off": {
                    "description": "Turn off all lights matching a name prefix. Response published on all_lights_off_reply",
                    "params": {"prefix": "Name prefix to filter lights (e.g. 'TVRoom')"}
                },
                "get_mqtt_description": {
                    "description": "Request the MQTT API description for this service. Response published on get_mqtt_description_reply",
                    "params": {}
                },
            },
            "announcements": {
                "get_lights_reply": {
                    "description": "Response to get_lights. JSON array of light state objects",
                    "payload": [{"name": "Light name", "state": "ON/OFF", "brightness": "0-255", "...": "other device-specific fields"}]
                },
                "get_switches_reply": {
                    "description": "Response to get_switches. JSON array of switch state objects",
                    "payload": [{"name": "Switch name", "state": "ON/OFF"}]
                },
                "all_lights_on_reply": {
                    "description": "Confirmation that all_lights_on completed",
                    "payload": {"status": "ok"}
                },
                "all_lights_off_reply": {
                    "description": "Confirmation that all_lights_off completed",
                    "payload": {"status": "ok"}
                },
                "get_mqtt_description_reply": {
                    "description": "The MQTT API description for this service",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
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
