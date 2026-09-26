""" Routes messages from zigbee2mqtt-like networks to callbacks """
from zzmw_lib.logs import build_logger
log = build_logger("Z2M")

import functools

# Bridge subtopics we receive (we subscribe to the whole network) but don't need
_IGNORED_BRIDGE_SUBTOPICS = (
    'bridge/state', 'bridge/extensions', 'bridge/logging', 'bridge/info', 'bridge/config', 'bridge/converters',
    'bridge/definitions', 'bridge/event', 'bridge/response/device/rename', 'bridge/response/health_check',
)


def _ignore_msg(_topic, _payload):
    pass


class Z2MTopicRouter:
    """
    Knows the MQTT topic layout of zigbee2mqtt-like networks, and routes each message to the callbacks registered
    for it. Callbacks are keyed by full topic ('<z2m_topic>/<subtopic>'), so a callback only gets messages from its
    own network, and are called as cb(subtopic, payload). Multiple callbacks can be active for the same topic (eg one
    to update a thing, another to forward the exact same message to a websocket).
    """
    def __init__(self):
        self._cbs = {}

    def add(self, z2m_topic, subtopic, cb):
        """ Register cb for messages on '<z2m_topic>/<subtopic>' """
        self._cbs.setdefault(f'{z2m_topic}/{subtopic}', []).append(cb)

    def add_bridge_rules(self, z2m_topic, on_devices_published):
        """ Register the bridge rules of a network: on_devices_published(subtopic, payload) gets its device lists;
        groups and other bridge messages are ignored. Do this before messages start arriving. """
        self.add(z2m_topic, 'bridge/devices', on_devices_published)
        self.add(z2m_topic, 'bridge/groups', functools.partial(self._ignore_groups, z2m_topic))
        for subtopic in _IGNORED_BRIDGE_SUBTOPICS:
            self.add(z2m_topic, subtopic, _ignore_msg)

    def _ignore_groups(self, z2m_topic, _topic, payload):
        for group in payload:
            try:
                gid = group['id']
                self.add(z2m_topic, f'{gid}/', _ignore_msg)
                self.add(z2m_topic, f'{gid}/availability', _ignore_msg)
            except:
                log.error("Malformed group message has no group id, payload '%s'", str(payload))

    def add_thing(self, thing, cb, availability_cb):
        """ Register cb for every topic a thing may use in its network: its name, its unaliased name and its address,
        plus their /set echoes; and availability_cb for their /availability reports. These often coincide (no alias;
        unnamed devices are named after their address), so register each distinct topic once, otherwise cb would run
        more than once per message. """
        for subtopic in dict.fromkeys((thing.name, thing.real_name, thing.address)):
            self.add(thing.z2m_topic, subtopic, cb)
            self.add(thing.z2m_topic, f'{subtopic}/set', cb)
            self.add(thing.z2m_topic, f'{subtopic}/availability', availability_cb)

    def ignore_thing(self, thing):
        """ Messages for this thing will be explicitly ignored. This is needed because we subscribe to the whole
        network, so we get every message it sends, but we don't care about some things. """
        self.add_thing(thing, _ignore_msg, _ignore_msg)

    def dispatch(self, z2m_topic, subtopic, payload):
        """ Call the callbacks for '<z2m_topic>/<subtopic>'. Returns False if there were none. """
        # Copy the list, so callbacks can add rules (eg bridge/groups) while we iterate
        matching_cbs = list(self._cbs.get(f'{z2m_topic}/{subtopic}', []))
        for cb in matching_cbs:
            cb(subtopic, payload)
        return len(matching_cbs) > 0
