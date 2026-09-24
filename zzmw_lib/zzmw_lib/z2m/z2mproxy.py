from zzmw_lib.logs import build_logger
log = build_logger("Z2M")

from zzmw_lib.z2m.light_helpers import monkeypatch_lights, monkeypatch_switches, identify_buttons, identify_sensors

from ctypes import c_int32
from datetime import datetime, timedelta

import dataclasses
import functools
import os
import signal

from .thing import parse_from_zigbee2mqtt, ZMW_NO_MQTT_BACKING

_DEFAULT_Z2M_TOPIC = 'zigbee2mqtt'

def _get_z2m_topics(cfg):
    """ List of network base topics: cfg['z2m_topics'] if set, otherwise just the default zigbee2mqtt topic """
    if 'z2m_topics' not in cfg:
        return [_DEFAULT_Z2M_TOPIC]

    topics = cfg['z2m_topics']
    if not isinstance(topics, list) or len(topics) == 0 or \
            not all(isinstance(t, str) and len(t) > 0 for t in topics):
        raise ValueError(f"z2m_topics must be a non-empty list of topic names, got {topics!r}")
    for t in topics:
        if t.endswith('/') or '#' in t or '+' in t or t == ZMW_NO_MQTT_BACKING:
            raise ValueError(f"z2m_topics entry {t!r} must be a plain base topic (no wildcards, no trailing '/')")
    for i, a in enumerate(topics):
        for j, b in enumerate(topics):
            # Dispatch is first-match, so a topic nested in another one would steal (or lose) its messages
            if i != j and (a == b or b.startswith(a + '/')):
                raise ValueError(f"z2m_topics entries {a!r} and {b!r} overlap, base topics must be distinct")
    return list(topics)

def _describe_origin(thing):
    """ Where a thing comes from, for logs """
    if thing.z2m_topic == ZMW_NO_MQTT_BACKING:
        return 'a virtual thing'
    return f"a thing from network '{thing.z2m_topic}'"

class Z2MProxy:
    """
    Proxy for interacting with Zigbee2MQTT devices.

    Discovers and tracks Zigbee devices, manages device state updates, and provides
    health monitoring for the Zigbee2MQTT bridge. Uses MQTT to communicate with
    the bridge and receives device announcements and state changes.

    Args:
        cfg: Configuration dict. 'z2m_topics' is a list of MQTT base topics, one per network (device names must be
             unique across networks). The first one is the primary network. Defaults to ['zigbee2mqtt'].
        mqtt: MqttProxy instance for MQTT communication
    """
    def __init__(self, cfg, mqtt, scheduler, cb_on_z2m_network_discovery=None, cb_is_device_interesting=None):
        self._z2m_topics = _get_z2m_topics(cfg)
        # Primary network: must be up on startup. We monitor this one is up.
        # TODO: Remove the main z2m topic once multi topic support is complete, so that we monitor ALL topics.
        self._main_z2m_topic = self._z2m_topics[0]
        self._z2m_topics_discovered = set()
        self._known_things = {}
        # Full MQTT topic ('<z2m_topic>/<subtopic>') -> list of callbacks, called as cb(subtopic, payload)
        self._z2m_topic_cbs = {}
        # Things we refused to register because their name is taken, already logged: {(z2m_topic, name, address)}
        self._rejected_things = set()
        self._init_subtopics()

        self._aliases = {} # Can be used to set up aliases to things if needed
        self._last_device_id = 0
        self._z2m_devices_discovered = False
        self._cb_on_z2m_network_discovery = cb_on_z2m_network_discovery
        self._cb_is_device_interesting = cb_is_device_interesting or (lambda x: True)

        self._scheduler = scheduler
        self._z2m_ping_timeout_minutes = 5
        # Last time each network sent anything, by topic. A network that never sent anything has no entry.
        self._z2m_last_msg_t = {}
        self._scheduler.add_job(
            self._z2m_connect_check,
            'date',
            run_date=datetime.now() + timedelta(seconds=3)
        )

        self._mqtt = mqtt
        for z2m_topic in self._z2m_topics:
            self._mqtt.subscribe_with_cb(z2m_topic, functools.partial(self._on_z2m_json_msg, z2m_topic))

    def _add_topic_cb(self, z2m_topic, subtopic, cb):
        """ Register cb for messages on '<z2m_topic>/<subtopic>'. Multiple callbacks can be active for the same
        topic (eg one to update a thing, another to forward the exact same message to a websocket). """
        self._z2m_topic_cbs.setdefault(f'{z2m_topic}/{subtopic}', []).append(cb)

    def _init_subtopics(self):
        """ Register the bridge rules of every network before starting the mqtt loop, so that the first handled
        message already has some rules """
        def _ignore_msg(_topic, _payload):
            pass
        def ignore_group_messages(z2m_topic, _topic, payload):
            for group in payload:
                try:
                    gid = group['id']
                    self._add_topic_cb(z2m_topic, f'{gid}/', _ignore_msg)
                    self._add_topic_cb(z2m_topic, f'{gid}/availability', _ignore_msg)
                except:
                    log.error("Malformed group message has no group id, payload '%s'", str(payload))
        for z2m_topic in self._z2m_topics:
            self._add_topic_cb(z2m_topic, 'bridge/devices', functools.partial(self._on_msg_device_list_published, z2m_topic))
            self._add_topic_cb(z2m_topic, 'bridge/groups', functools.partial(ignore_group_messages, z2m_topic))
            for subtopic in ('bridge/state', 'bridge/extensions', 'bridge/logging', 'bridge/info', 'bridge/config',
                             'bridge/converters', 'bridge/definitions', 'bridge/event',
                             'bridge/response/device/rename', 'bridge/response/health_check'):
                self._add_topic_cb(z2m_topic, subtopic, _ignore_msg)


    def _z2m_connect_check(self):
        if self._main_z2m_topic not in self._z2m_topics_discovered:
            # If Z2M didn't publish its network, crash so that we try again.
            # We could unsubscribe and subscribe to z2m/bridge/devices, but since this
            # hasn't ever happend it's probably safe to kill and restart instead of retrying
            log.critical("Z2M didn't publish a network on '%s'. Is Z2M down? "
                         "This can happen if an mqtt message is lost, "
                         "and it's typically benign if a restart of the service fixes the problem.", self._main_z2m_topic)
            os.kill(os.getpid(), signal.SIGTERM)
            return

        # Only the primary network is required: others may come up later (or be test topics with no network)
        for z2m_topic in self._z2m_topics:
            if z2m_topic not in self._z2m_topics_discovered:
                log.warning("Z2M network on '%s' hasn't published its devices yet, its things will be missing "
                            "until it does", z2m_topic)

        self._scheduler.add_job(
            self._z2m_health_check,
            'interval',
            minutes=self._z2m_ping_timeout_minutes,
            id='z2m_health_check'
        )

    def _z2m_health_check(self):
        """ Single job for all networks: complain about each one that has gone quiet """
        now = datetime.now()
        for z2m_topic in self._z2m_topics:
            last_msg_t = self._z2m_last_msg_t.get(z2m_topic)
            if last_msg_t is None:
                log.error("Z2M network on '%s' hasn't sent any message since startup, is it alive?", z2m_topic)
            elif now - last_msg_t > timedelta(minutes=self._z2m_ping_timeout_minutes):
                log.error("Z2M network on '%s' hasn't sent a message in more than %d minutes, is it alive?",
                          z2m_topic, self._z2m_ping_timeout_minutes)

    def _on_z2m_json_msg(self, z2m_topic, topic, payload):
        """ Handle a message from the network on z2m_topic; topic is the subtopic (eg a thing name). Rules are keyed
        by full topic, so a thing only gets messages from its own network. """
        self._z2m_last_msg_t[z2m_topic] = datetime.now()
        # Copy the list, so callbacks can add rules (eg bridge/groups) while we iterate
        matching_cbs = list(self._z2m_topic_cbs.get(f'{z2m_topic}/{topic}', []))
        for cb_for_topic in matching_cbs:
            cb_for_topic(topic, payload)

        if len(matching_cbs) == 0:
            log.warning('Unhandled MQTT message on topic %s/%s', z2m_topic, topic)


    def _on_msg_device_list_published(self, z2m_topic, _topic, payload):
        log.info('Zigbee2Mqtt bridge on %s published list of devices', z2m_topic)
        device_added = False
        for jsonthing in payload:
            self._last_device_id += 1
            thing = parse_from_zigbee2mqtt(self._last_device_id, jsonthing, z2m_topic,
                                           known_aliases=self._aliases)
            if self._is_thing_unknown(thing):
                if self._cb_is_device_interesting(thing):
                    self._register(thing)
                    device_added = True
                else:
                    self._reg_to_ignore(thing)

        is_first_discovery = not self._z2m_devices_discovered
        self._z2m_devices_discovered = True
        self._z2m_topics_discovered.add(z2m_topic)

        if not device_added:
            log.info('Bridge published network definition. No new devices were found.')

        monkeypatch_lights(self)
        monkeypatch_switches(self)
        identify_buttons(self)
        identify_sensors(self)
        if not self._cb_on_z2m_network_discovery:
            log.info('Zigbee2Mqtt network,%s device definition published. Discovered %d things.',
                     " first" if is_first_discovery else "", len(self._known_things.keys()))
        else:
            self._cb_on_z2m_network_discovery(is_first_discovery, self._known_things)


    def _is_thing_unknown(self, thing):
        known = self._known_things.get(thing.name)
        if known is None:
            return True

        if thing.name != thing.real_name and thing.real_name not in self._known_things:
            log.warning(
                "Thing with MQTT name %s is being ignored, because it's aliased by %s. "
                "Aliasing things to the same name is a bad idea.", thing.real_name, thing.name)
        elif known.z2m_topic == thing.z2m_topic and known.address == thing.address:
            log.debug(
                'Ignoring registration for %s, thing already known',
                thing.name)
        else:
            self._reject_thing(thing, known)
        return False

    def _reject_thing(self, thing, known):
        """ thing's name is already taken by a different thing: keep the first one, and ignore messages for the new
        one (only in its own network, so they don't update the known thing). Logs once per rejected thing. """
        key = (thing.z2m_topic, thing.name, thing.address)
        if key in self._rejected_things:
            return
        self._rejected_things.add(key)
        self._reg_to_ignore(thing)

        if known.z2m_topic == thing.z2m_topic:
            log.warning(
                "Thing %s on '%s' now has address %s, but %s is already registered for it (was the device replaced?). "
                "Keeping the old one, restart the service to pick up the new one.",
                thing.name, thing.z2m_topic, thing.address, known.address)
        else:
            log.error(
                "Thing name %s from network '%s' is already used by %s. Names must be unique across networks, "
                "ignoring the one from '%s'.",
                thing.name, thing.z2m_topic, _describe_origin(known), thing.z2m_topic)


    def _register(self, thing):
        """ Add or replace a thing to the MQTT registry """
        self._register_or_replace(thing)
        if thing.name != thing.real_name:
            log.debug(
                'Registered Zigbee2Mqtt device %s (alias for %s) ID %d',
                thing.name,
                thing.real_name,
                thing.thing_id)
        else:
            log.debug(
                'Registered Zigbee2Mqtt device %s ID %d',
                thing.name,
                thing.thing_id)
        return True

    def _register_or_replace(self, thing):
        """ Add or replace a thing to the MQTT registry """
        self._known_things[thing.name] = thing
        self._add_thing_topic_cbs(thing, thing.on_mqtt_update)

        # We're never unsubscribing if the thing goes away, but the entire service will never forget unreg'ed things either
        # so it's fine. It'd require a bit of refactoring to properly track registered objects, and since this should very
        # rarely happen, we can ask the user to reboot the services when the network changes.
        self._mqtt.subscribe_with_cb(thing.extras.get_mqtt_topic(), thing.extras.on_mqtt_update)

    def _reg_to_ignore(self, thing):
        """ Messages for this thing will be explicitlly ignored. This is needed because we register for the root mqtt
        topic, so we get all of the messages that z2m sends, but we want to ignore some of them. Some day, we can
        register only to interesting messages. """
        def _ignore_msg(_topic, _payload):
            pass
        self._add_thing_topic_cbs(thing, _ignore_msg)

    def _add_thing_topic_cbs(self, thing, cb):
        """ Register cb for every topic a thing may use: its name, its unaliased name and its address, plus their
        /set echoes. These often coincide (no alias; unnamed devices are named after their address), so register each
        distinct topic once, otherwise cb would run more than once per message. """
        for subtopic in dict.fromkeys((thing.name, thing.real_name, thing.address)):
            self._add_topic_cb(thing.z2m_topic, subtopic, cb)
            self._add_topic_cb(thing.z2m_topic, f'{subtopic}/set', cb)

    def register_virtual_thing(self, thing):
        """Register a virtual (non-zigbee) thing.

        Virtual things are not backed by zigbee2mqtt devices. They only have extras,
        and are used for external data sources like weather APIs.

        Args:
            thing: A thing created with create_virtual_thing()
        """
        if thing.name in self._known_things:
            log.error("Virtual thing %s is already used by %s, ignoring new registration",
                      thing.name, _describe_origin(self._known_things[thing.name]))
            return

        self._known_things[thing.name] = thing
        # Subscribe to extras topic so other services' broadcasts update our local state
        self._mqtt.subscribe_with_cb(thing.extras.get_mqtt_topic(), thing.extras.on_mqtt_update)
        log.info("Registered virtual thing: %s", thing.name)

    def get_known_things_hash(self):
        """ Returns a 32 bit hash of the names of all known things, to let clients determine if the
        network of known devices has changed. Note this doesn't update on actions change, and is not
        guaranteed to be colision free. """
        sorted_names = sorted(self.get_thing_names())
        nethash = 0
        for name in sorted_names:
            chr_list = list(name)
            for chr_as_int in list(map(ord, chr_list)):
                nethash = c_int32((nethash << 2) - nethash + chr_as_int).value
        return str(nethash)

    def get_thing_names(self):
        """ Get names of all known things """
        return list(self._known_things.keys())

    def get_world_state(self):
        """ Get the state of all the world """
        return [{name: thing.get_json_state()} for name,thing in self._known_things.items()]

    def get_thing(self, thing_name):
        return self._known_things[thing_name]

    def get_things_if(self, cb):
        return list(filter(cb, self._known_things.values()))

    def get_all_registered_things(self):
        return self._known_things.values()

    def get_thing_meta(self, thing_name):
        try:
            thing = self._known_things[thing_name]
        except KeyError:
            return None

        try:
            # Give the object a chance to dictify itself
            return thing.dictify()
        except AttributeError:
            # If thing doesn't define dictify, default to dataclasses
            # copying
            return dataclasses.asdict(thing)

    def broadcast_things(self, things_or_names):
        for t in things_or_names:
            self.broadcast_thing(t)

    def broadcast_thing(self, thing_or_name):
        """
        Notify the bridge that a thing has been updated, and it's time to have
        its state propagated to MQTT-land. Function accepts either a thing or a
        name as input (if a thing is received, no checks are done to verify it's
        a valid and known thing).
        """
        if isinstance(thing_or_name, str):
            thing = self.get_thing(thing_or_name)
        else:
            thing = thing_or_name

        # Broadcast regular zigbee2mqtt values, to the network this thing belongs to
        topic = f'{thing.z2m_topic}/{thing.real_name}/set'
        status = thing.make_mqtt_status_update()
        if len(status.keys()) != 0 and thing.z2m_topic == ZMW_NO_MQTT_BACKING:
            log.error('Thing %s has no MQTT network, dropping update %s', thing.name, status)
        elif len(status.keys()) != 0:
            self._mqtt.broadcast(topic, status)
            log.debug(
                'Thing %s%s is bcasting update topic[%s]:"%s"',
                thing.name,
                f'(an alias for {thing.real_name})' if thing.real_name != thing.name else '',
                topic,
                status)

        # Broadcast extras (virtual metrics)
        extras_status = thing.extras.make_mqtt_status_update()
        if len(extras_status.keys()) != 0:
            self._mqtt.broadcast(thing.extras.get_mqtt_topic(), extras_status)
            # Some sensors can be quite spammy, so this will be a very spammy log too
            # log.debug('Thing bcasting extras: %s %s', thing.extras.get_mqtt_topic(), extras_status)
