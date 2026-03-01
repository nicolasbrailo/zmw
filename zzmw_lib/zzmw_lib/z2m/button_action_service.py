import json
import os
import pathlib
from flask import request

from zzmw_lib.z2m.helpers import bind_callbacks_to_z2m_actions
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger
from zzmw_lib.z2m.z2mproxy import Z2MProxy

log = build_logger("ButtonActionService")

class ButtonActionService(ZmwMqttService):
    """ Helper to implement a service that will enable buttons and scenes (consider scenes like a type of button!)
    Extend this class and
    1. Create a methode that starts with `_scene_` (eg _scene_all_off) to expose a scene
    2. Create a method called '_z2m_cb_$thingName_$actionName' to bind a callback to a specific action (eg a button
       called Foo that triggers an action Bar should be called _z2m_cb_Foo_Bar
    The scenes and buttons will be exposed through a www API. The buttons cb's will be invoked when the z2m thing event
    is triggered.
    Start the service with service_runner_with_www(YourClass)
    """
    def __init__(self, cfg, www, www_path, scheduler, svc_deps):
        super().__init__(cfg, svc_topic=None, scheduler=scheduler, svc_deps=svc_deps)

        # Set up www directory and endpoints
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/buttons_state', self.get_buttons_state)
        www.serve_url('/ls_scenes', self.get_scenes)
        www.serve_url('/apply_scene', self.apply_scene, methods=['PUT'])
        www.serve_url('/trigger_action', self.trigger_action, methods=['POST'])

        self._unbound_callbacks = []
        self._bound_callbacks = []
        self._discovered_btn_actions = {}

        self._z2m = Z2MProxy(cfg, self, scheduler, cb_on_z2m_network_discovery=self._on_z2m_network_discovery)

    def _on_z2m_network_discovery(self, _is_first_discovery, known_things):
        """Handle Z2M network discovery and bind button callbacks."""
        log.info("Z2M network discovered, there are %d things", len(known_things))
        self._unbound_callbacks, self._bound_callbacks = bind_callbacks_to_z2m_actions(self, '_z2m_cb_', known_things, global_pre_cb=self._discover_btn_actions)
        self._unbound_callbacks = sorted(self._unbound_callbacks)
        self._bound_callbacks = sorted(self._bound_callbacks)

    def _discover_btn_actions(self, thing_name, action, value):
        log.debug("Trigger %s.%s = %s", thing_name, action, value)
        if f'{thing_name}_{action}' not in self._discovered_btn_actions:
            self._discovered_btn_actions[f'{thing_name}_{action}'] = set()
        self._discovered_btn_actions[f'{thing_name}_{action}'].add(value)

    def get_buttons_state(self):
        """Flask endpoint to get buttons and their binding status"""
        return json.dumps({
            'bound_actions': self._bound_callbacks,
            'unbound_actions': self._unbound_callbacks,
            'discovered_actions': {k: list(v) for k, v in self._discovered_btn_actions.items()},
        })

    def get_scenes(self):
        # Return all methods in this class starting with _scene_
        return [name[len('_scene_'):] for name in dir(self) if name.startswith('_scene_') and callable(getattr(self, name))]

    def apply_scene(self):
        scene_name = request.args.get('scene')
        if not scene_name:
            return json.dumps({'error': 'Missing scene parameter'}), 400
        method_name = f'_scene_{scene_name}'
        method = getattr(self, method_name, None)
        if method and callable(method):
            method()
            return json.dumps({'success': True})
        return json.dumps({'error': f'Unknown scene: {scene_name}'}), 404

    def trigger_action(self):
        """Flask endpoint to trigger a button action from the UI"""
        data = request.get_json()
        if not data or 'button_name' not in data or 'action_value' not in data:
            return json.dumps({'error': 'Missing button_name or action_value'}), 400

        button_name = data['button_name']
        action_value = data['action_value']

        if button_name not in self._bound_callbacks:
            return json.dumps({'error': f'Unknown button: {button_name}'}), 404

        # Get the callback method
        callback = getattr(self, f'_z2m_cb_{button_name}', None)
        if callback:
            log.info("Triggering action %s with value %s from UI", button_name, action_value)
            callback(action_value)
            return json.dumps({'success': True, 'message': f'Triggered {button_name} with {action_value}'})

        return json.dumps({'error': 'Could not trigger action'}), 500

