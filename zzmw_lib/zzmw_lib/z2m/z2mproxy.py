from zzmw_lib.logs import build_logger
log = build_logger("Z2M")

from zzmw_lib.z2m.light_helpers import monkeypatch_lights, monkeypatch_switches, identify_buttons, identify_sensors

from ctypes import c_int32
from datetime import datetime, timedelta

import dataclasses
import os
import signal

from .thing import parse_from_zigbee2mqtt

class Z2MProxy:
    """
    Proxy for interacting with Zigbee2MQTT devices.

    Discovers and tracks Zigbee devices, manages device state updates, and provides
    health monitoring for the Zigbee2MQTT bridge. Uses MQTT to communicate with
    the bridge and receives device announcements and state changes.

    Args:
        cfg: Configuration dict
        mqtt: MqttProxy instance for MQTT communication
        topic: MQTT topic prefix for Zigbee2MQTT (default: 'zigbee2mqtt')
    """
    def __init__(self, cfg, mqtt, scheduler, topic='zigbee2mqtt',
                 cb_on_z2m_network_discovery=None, cb_is_device_interesting=None):
        self._z2m_topic = topic
        self._known_things = {}
        self._z2m_subtopic_cbs = []
        self._init_subtopics()

        self._aliases = {} # Can be used to set up aliases to things if needed
        self._last_device_id = 0
        self._z2m_devices_discovered = False
        self._cb_on_z2m_network_discovery = cb_on_z2m_network_discovery
        self._cb_is_device_interesting = cb_is_device_interesting or (lambda x: True)

        self._scheduler = scheduler
        self._z2m_ping_timeout_minutes = 5
        self._scheduler.add_job(
            self._z2m_connect_check,
            'date',
            run_date=datetime.now() + timedelta(seconds=3)
        )

        self._mqtt = mqtt
        self._mqtt.subscribe_with_cb(self._z2m_topic, self._on_z2m_json_msg)

    def _init_subtopics(self):
        """ Register a callback for an MQTT topic. Multiple callbacks can be active
        for the same topic (eg one to update a thing, another to forward the
        exact same message to a websocket).
        Register default rules before starting mqtt loop, so that the first handled
        message already has some rules """
        def _ignore_msg(_topic, _payload):
            self._z2m_last_msg_t = datetime.now()
        def ignore_group_messages(_topic, payload):
            for group in payload:
                try:
                    gid = group['id']
                    self._z2m_subtopic_cbs.append((f'{gid}/', _ignore_msg))
                    self._z2m_subtopic_cbs.append((f'{gid}/availability', _ignore_msg))
                except:
                    log.error("Malformed group message has no group id, payload '%s'", str(payload))
        self._z2m_subtopic_cbs.append(('bridge/devices', self._on_msg_device_list_published))
        self._z2m_subtopic_cbs.append(('bridge/groups', ignore_group_messages))
        self._z2m_subtopic_cbs.append(('bridge/state', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/extensions', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/logging', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/info', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/config', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/converters', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/definitions', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/event', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/response/device/rename', _ignore_msg))
        self._z2m_subtopic_cbs.append(('bridge/response/health_check', _ignore_msg))


    def _z2m_connect_check(self):
        if not self._z2m_devices_discovered:
            # If Z2M didn't publish its network, crash so that we try again.
            # We could unsubscribe and subscribe to z2m/bridge/devices, but since this
            # hasn't ever happend it's probably safe to kill and restart instead of retrying
            log.critical("Z2M didn't publish a network. Is Z2M down? "
                         "This can happen if an mqtt message is lost, "
                         "and it's typically benign if a restart of the service fixes the problem.")
            os.kill(os.getpid(), signal.SIGTERM)
            return

        self._scheduler.add_job(
            self._z2m_health_check,
            'interval',
            minutes=self._z2m_ping_timeout_minutes,
            id='recurring_job'
        )

    def _z2m_health_check(self):
        if datetime.now() - self._z2m_last_msg_t > timedelta(minutes=self._z2m_ping_timeout_minutes):
            log.error("Z2M hasn't sent a message in more than %d minutes, is it alive?", self._z2m_ping_timeout_minutes)

    def _on_z2m_json_msg(self, topic, payload):
        self._z2m_last_msg_t = datetime.now()
        # Filter CBs so we can apply them without worrying about a callback
        # changing the rules
        matching_cbs = []
        for rule, cb_for_topic in self._z2m_subtopic_cbs:
            if topic == rule:
                # log.debug('Applying rule %s for topic %s', rule, topic)
                matching_cbs.append(cb_for_topic)

        for cb_for_topic in matching_cbs:
            cb_for_topic(topic, payload)

        if len(matching_cbs) == 0:
            log.warning('Unhandled MQTT message on topic %s', topic)


    def _on_msg_device_list_published(self, _topic, payload):
        log.info('Zigbee2Mqtt bridge published list of devices')
        device_added = False
        for jsonthing in payload:
            self._last_device_id += 1
            thing = parse_from_zigbee2mqtt(self._last_device_id, jsonthing, known_aliases=self._aliases)
            if self._is_thing_unknown(thing):
                if self._cb_is_device_interesting(thing):
                    self._register(thing)
                    device_added = True
                else:
                    self._reg_to_ignore(thing)

        is_first_discovery = not self._z2m_devices_discovered
        self._z2m_devices_discovered = True

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
        if thing.name in self._known_things:
            if thing.name != thing.real_name and thing.real_name not in self._known_things:
                log.warning(
                    "Thing with MQTT name %s is being ignored, because it's aliased by %s. "
                    "Aliasing things to the same name is a bad idea.", thing.real_name, thing.name)
            else:
                log.debug(
                    'Ignoring registration for %s, thing already known',
                    thing.name)
            return False
        return True


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
        self._z2m_subtopic_cbs.append((thing.name, thing.on_mqtt_update))
        if thing.real_name != thing.name:
            # Add a second callback for aliases
            self._z2m_subtopic_cbs.append((thing.real_name, thing.on_mqtt_update))
        self._z2m_subtopic_cbs.append((thing.address, thing.on_mqtt_update))
        self._z2m_subtopic_cbs.append((f'{thing.real_name}/set', thing.on_mqtt_update))
        self._z2m_subtopic_cbs.append((f'{thing.name}/set', thing.on_mqtt_update))
        self._z2m_subtopic_cbs.append((f'{thing.address}/set', thing.on_mqtt_update))

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
        self._z2m_subtopic_cbs.append((thing.name, _ignore_msg))
        if thing.real_name != thing.name:
            # Add a second callback for aliases
            self._z2m_subtopic_cbs.append((thing.real_name, _ignore_msg))
        self._z2m_subtopic_cbs.append((thing.address, _ignore_msg))
        self._z2m_subtopic_cbs.append((f'{thing.real_name}/set', _ignore_msg))
        self._z2m_subtopic_cbs.append((f'{thing.name}/set', _ignore_msg))
        self._z2m_subtopic_cbs.append((f'{thing.address}/set', _ignore_msg))

    def register_virtual_thing(self, thing):
        """Register a virtual (non-zigbee) thing.

        Virtual things are not backed by zigbee2mqtt devices. They only have extras,
        and are used for external data sources like weather APIs.

        Args:
            thing: A thing created with create_virtual_thing()
        """
        if thing.name in self._known_things:
            log.error("Virtual thing %s is already registered or duplicates a name, ignoring new registration", thing.name)
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

        # Broadcast regular zigbee2mqtt values
        topic = f'{self._z2m_topic}/{thing.real_name}/set'
        status = thing.make_mqtt_status_update()
        if len(status.keys()) != 0:
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
