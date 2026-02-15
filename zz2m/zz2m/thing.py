""" Global representation of Zigbee things """

from dataclasses import dataclass
from typing import Callable
import json
from json import JSONDecodeError

from zzmw_lib.logs import build_logger
from zz2m.thing_extras import ThingExtras

log = build_logger("Z2M")

_Z2M_IGNORE_ACTIONS = ['update']


class ActionDict(dict):
    """
    An action dict is just a normal dict, but raises an AttributeError
    instead of a KeyError if an action is missing. This is to make it
    easier to describe when a thing doesn't exist (KeyError) from when
    a thing is valid but doesn't support an action (AttributeError)
    """

    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError as exc:
            raise AttributeError(f'{key} is not a known action') from exc

    def dictify(self):
        """ Get metadata on supported actions """
        return {k: v.dictify() for k, v in self.items()}


class IgnoredActionValue:
    """Value object for ignored composite fields that don't match the schema"""
    def _set_value(self, val):
        # No-op: silently discard updates to ignored fields
        pass

    def get_value(self):
        return None

    def debug_str(self):
        return "IGNORED"


class IgnoredAction:
    """Action object for out-of-schema composite fields"""
    def __init__(self, field_name):
        self.name = field_name
        self.value = IgnoredActionValue()

    def dictify(self):
        return self.debug_str()

    def debug_str(self):
        return f"{self.name}=IGNORED"


@dataclass(frozen=False)
class Zigbee2MqttThing:
    """
    Describes a zigbee2mqtt object. Holds a map of actions (the features/variables/
    actions/reports/etc that a zigbee2mqtt object supports)
    """
    thing_id: int
    address: str
    name: str
    real_name: str
    broken: bool
    manufacturer: str
    model: str
    description: str
    thing_type: str
    actions: ActionDict
    extras: ThingExtras = None
    is_zigbee_mqtt: bool = True
    # Will print extra verbose logs for each MQTT action
    debug_mqtt_actions: bool = False
    # Callback whenever any action is updated from MQTT
    on_any_change_from_mqtt: Callable = None
    # Like on_any_change_from_mqtt, but only fires when state actually differs
    on_state_change_from_mqtt: Callable = None
    _last_notified_state: str = None
    user_defined: map = None

    def dictify(self):
        """ Get metadata on this thing """
        return {
            "thing_id": self.thing_id,
            "address": self.address,
            "name": self.name,
            "real_name": self.real_name,
            "broken": self.broken,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "description": self.description,
            "thing_type": self.thing_type,
            "actions": self.actions.dictify(),
            "is_zigbee_mqtt": self.is_zigbee_mqtt,
            "user_defined": self.user_defined,
        }

    def debug_str(self):
        """ Pretty print self, recursively """
        if self.broken:
            return f'Thing {self.name} is broken'

        descr = self.description
        if self.thing_type is not None:
            descr = f'{self.thing_type} ({self.description})'

        acts = '\n'.join(['\t' + self.actions[name].debug_str()
                          for name in self.actions])
        if len(acts) == 0:
            acts = '\t[]'

        return f'Thing {self.name} ID{self.thing_id} is a {descr}. Actions:\n{acts}'

    def on_mqtt_update(self, topic: str, msg: dict):
        """
        Parses an MQTT message, updates the local state to reflect the changes.
        If an observer was registered for (one of) the changed actions of this
        object, the callback will be invoked only if the change was accepted.
        Note the topic may either be the name, addr or alias of this thing
        """
        changes = []
        thing_updated = False
        # Signals that iterating over this message failed, and it needs to be retried
        needs_retry = False
        for mqtt_msg_field in msg:
            try:
                val = msg[mqtt_msg_field]
                changed_action = self._set(mqtt_msg_field, val, set_by_user=False)
                # Keep a list of all changes' callbacks
                if changed_action is not None:
                    thing_updated = True
                    changes.append((changed_action.value.on_change_from_mqtt, val))
            except AttributeError:
                # Some battery powered devices don't seem to respect their
                # schema?
                if mqtt_msg_field == 'battery':
                    self.battery = val
                elif mqtt_msg_field == 'voltage':
                    self.voltage = val
                else:
                    log.warning(
                        'Unsupported action in mqtt message: thing %s ID %d has no %s, will add it',
                        self.name,
                        self.thing_id,
                        mqtt_msg_field)
                    log.debug('Exception in MQTT message %s', msg)
                    # A thing triggered an action that wasn't declared in its schema. Add it to the schema and retry.
                    def act_set(x):
                        self.actions[mqtt_msg_field].value._current = x
                    self.actions[mqtt_msg_field] = make_user_defined_zigbee2mqttaction(
                                thing_name=self.name,
                                name=mqtt_msg_field,
                                description=f"Out-of-schema action '{mqtt_msg_field}'",
                                setter=act_set,
                                getter=lambda: self.actions[mqtt_msg_field].value._current)
                    # We added an action, but a message may contain multiple missing actions. When this happens,
                    # exit the for loop and retry the entire message. Alternatively, we can try exiting the catch
                    # so that a new missing attribute will be processed, but retrying the entire message seems simpler
                    needs_retry = True
                    break

        if needs_retry:
            self.on_mqtt_update(topic, msg)

        if self.debug_mqtt_actions:
            if len(changes) != 0:
                log.debug(
                    'MQTT message updated thing %s ID %d: %s',
                    self.name,
                    self.thing_id,
                    msg)
            else:
                log.debug(
                    'MQTT message ignored by thing %s ID %d: %s',
                    self.name,
                    self.thing_id,
                    msg)

        # Once the update is done, invoke user callbacks. At this point
        # * The update is fully complete
        # * If the callback throws, we can let the exception propagate safely
        for cb_mqtt_chg, val in changes:
            if cb_mqtt_chg is not None:
                cb_mqtt_chg(val)

        if thing_updated and self.on_any_change_from_mqtt is not None:
            self.on_any_change_from_mqtt(self)

        if thing_updated and self.on_state_change_from_mqtt is not None:
            snapshot = json.dumps(self.get_json_state(), sort_keys=True)
            if snapshot != self._last_notified_state:
                self._last_notified_state = snapshot
                self.on_state_change_from_mqtt(self)

    def set(self, key, val):
        """ Set value (by user). Propagates to value object, applies metadata-validation """
        if self.debug_mqtt_actions:
            log.debug('User setting %s[%d].%s = %s', self.name, self.thing_id, key, val)
        self._set(key, val, set_by_user=True)

    def _set(self, key, val, set_by_user=True):
        for _act_name, action in self.actions.items():
            if action.accepts_value(key, val):
                # log.debug('Action %s[%d].%s accepts set %s = %s from %s',
                #             self.name, self.thing_id, _act_name, key, val,
                #             'user' if set_by_user else 'MQTT')
                if set_by_user:
                    action.set_value(val)
                else:
                    action.set_value_from_mqtt_update(val)
                return action

        if key in _Z2M_IGNORE_ACTIONS:
            # Signal no action has been changed
            return None

        raise AttributeError(
            f'{self.name}[{self.thing_id}] has no action {key} {self.debug_str()}')

    def get(self, key):
        """ Gets current state of an action (throws if action doesn't exist) """
        return self.actions[key].value.get_value()

    def get_json_state(self):
        """ Gets known state of all actions (if state isn't null) """
        state = {}
        for action_name in self.actions:
            val = self.actions[action_name].get_value()
            if val is not None:
                state.update(val)
        state['thing_name'] = self.name
        state['extras'] = self.extras.get_all()
        return state

    def make_mqtt_status_update(self):
        """ Prepares a map with actions that need their state propagated to MQTT """
        state = {}
        for action_name in self.actions:
            state.update(self.actions[action_name].make_mqtt_status_update())
        return state


@dataclass(frozen=False)
class Zigbee2MqttActionValue:
    """
    Holds metadata and current value for an action. The metadata describes
    the action (ie datatype, limits, supported values...)
    If the value is updated by the user, the "needs propagation" flag is
    set, until the method 'make_mqtt_status_update' is called. At this point,
    it's assumed that a state update has been sent to the MQTT server.
    If a data race happens between an incoming MQTT update and a user update,
    the user update wins: the "needs propagation" flag won't be cleared, and
    the user changes will be retained.
    """
    thing_name: str  # Only needed to print error messages
    meta: dict
    _current: object = None
    _needs_mqtt_propagation: bool = False
    # Triggered whenever this action is updated from MQTT
    on_change_from_mqtt: Callable = None

    def dictify(self):
        """ Meta data on this thing's method's current value """
        return {
            "thing_name": self.thing_name,
            "meta": self.meta,
            "_current": self._current,
            "_needs_mqtt_propagation": self._needs_mqtt_propagation,
        }

    def debug_str(self):
        """ Pretty print """
        presets = ''
        if 'presets' in self.meta:
            lst = ','.join(
                [f'{preset["name"]}={preset["value"]}' for preset in self.meta['presets']])
            presets = f': presets={{{lst}}}'

        if self.meta['type'] == 'binary':
            return f'{self._current} {{Binary:[{self.meta["value_on"]}|{self.meta["value_off"]}]}}'
        if self.meta['type'] == 'numeric':
            typedesc = f'{{Numeric:[{self.meta["value_min"]}:{self.meta["value_max"]}]}}{presets}'
            return f'{self._current} {typedesc}'
        if self.meta['type'] == 'enum':
            vals = '|'.join(self.meta['values'])
            return f'{self._current} {{Enum:[{vals}]}}'
        if self.meta['type'] == 'composite':
            sub_dbgs = [self.meta['composite_actions'][action].debug_str()
                        for action in self.meta['composite_actions']]
            sub_dbgs = ';'.join(sub_dbgs)
            return f'{self._current} {{Composite: {sub_dbgs}}}'
        if self.meta['type'] == 'list':
            item_type = self.meta.get('item_type', {}).get('type', 'unknown')
            length_info = ''
            if self.meta.get('length_min') is not None or self.meta.get('length_max') is not None:
                length_info = f'[{self.meta.get("length_min", 0)}:{self.meta.get("length_max", "∞")}]'
            current_len = len(self._current) if self._current else 0
            return f'{current_len} items {{List{length_info} of {item_type}}}'
        if self.meta['type'] == 'user_defined':
            return f'User defined function {self.meta["on_get"]()}'

        return f'{self._current} UNKNOWN ({self.meta["type"]})'

    def set_value(self, val):
        """
        Propagate set value for metadata validation, set if succeed. If another
        set() is pending and hasn't been propagated to MQTT, the previous set()
        will be lost. Probably.
        """
        # The set may fail, but it's a good enough heuristic: if a propagation
        # isn't needed, there's no bad side effect other than an extra message
        # log.debug('User set %s.action = %s', self.thing_name, val)
        self._needs_mqtt_propagation = True

        # Values for composites may come as a string (eg from Flask) instead of
        # a dict
        if self.meta['type'] == 'composite' and isinstance(val, str):
            try:
                tmp = json.loads(val)
                val = tmp
            except JSONDecodeError:
                # This wasn't a JSON after all
                pass

        return self._set_value(val, from_mqtt=False)

    def set_value_from_mqtt_update(self, val):
        """
        Copy update from MQTT land. If a user update is pending, ignore.
        """
        if self._needs_mqtt_propagation:
            # If a user update is pending, let the user change win
            log.error('Race condition on %s: received MQTT update '
                         'while user update pending broadcast - %s',
                         self.thing_name, self.debug_str())
            return

        try:
            self._set_value(val, from_mqtt=True)
        except ValueError as ex:
            log.error(ex)

    def _set_value(self, val, from_mqtt=False):
        def log_bad_set():
            raise ValueError(
                f'{self.thing_name} received invalid value {val} - {self.debug_str()}')

        # If action has presets, and current val is a preset name, replace by
        # preset
        if 'presets' in self.meta:
            for preset in self.meta['presets']:
                if preset['name'] == val:
                    val = preset['value']
                    break

        # Binaries may not be true|false, replace by the keyword
        # Binaries need some extra magic
        if self.meta['type'] == 'binary':
            if isinstance(val, bool):
                self._current = val
            elif val == self.meta['value_on']:
                self._current = True
            elif val == self.meta['value_off']:
                self._current = False
            elif isinstance(val, str) and val.lower() in ['true', '1']:
                self._current = True
            elif isinstance(val, str) and val.lower() in ['false', '0']:
                self._current = False
            else:
                log_bad_set()
            return

        if self.meta['type'] == 'numeric':
            num_val = int(val)
            if (self.meta['value_min'] is not None) and (
                    num_val < self.meta['value_min']):
                if from_mqtt:
                    log.warning('%s received out-of-range value %s (min %s), '
                                'clamping - %s', self.thing_name, val,
                                self.meta['value_min'], self.debug_str())
                    val = self.meta['value_min']
                else:
                    log_bad_set()
            if (self.meta['value_max'] is not None) and (
                    num_val > self.meta['value_max']):
                if from_mqtt:
                    log.warning('%s received out-of-range value %s (max %s), '
                                'clamping - %s', self.thing_name, val,
                                self.meta['value_max'], self.debug_str())
                    val = self.meta['value_max']
                else:
                    log_bad_set()
            self._current = val
            return

        if self.meta['type'] == 'enum':
            if val in self.meta['values']:
                self._current = val
            elif len(self.meta['values']) == 0:
                # Some things seem to have no metadata for enums, so don't raise an error
                log.warning(
                    'Thing "%s" received enum val "%s", but valid values set is empty', self.thing_name, val)
                self._current = val
            else:
                log_bad_set()
            return

        if self.meta['type'] == 'composite':
            for key in val:
                # The safest option is to recursively call _set_value for a
                # composite child. We could also call action.set_value, but
                # we'd need to carry a flag to know if this call came first
                # from MQTT or from the user, which may risk a race condition
                # on the value.
                # pylint: disable=protected-access
                if not key in self.meta['composite_actions']:
                    log.warning(f'{self.thing_name} ignore received value {key} = {val[key]}, but {key} is not declared in the schema - {self.debug_str()}. Will ignore this message.')
                    self.meta['composite_actions'][key] = IgnoredAction(key)
                    return
                if isinstance(self.meta['composite_actions'][key], IgnoredAction):
                    return
                self.meta['composite_actions'][key].value._set_value(val[key])
            return

        if self.meta['type'] == 'user_defined':
            self.meta["on_set"](val)
            return

        if self.meta['type'] == 'list':
            if not isinstance(val, list):
                log_bad_set()
            # Validate length constraints if specified
            if self.meta.get('length_min') is not None and len(val) < self.meta['length_min']:
                log_bad_set()
            if self.meta.get('length_max') is not None and len(val) > self.meta['length_max']:
                log_bad_set()
            # Store the list directly - zigbee2mqtt will validate item contents
            self._current = val
            return

        log.error('Thing %s has an unsuported action: %s',
                     self.thing_name, self.meta["type"])
        self._current = val

    def get_value(self):
        """ Gets immediate value, or build composite value """
        if self.meta['type'] == 'user_defined':
            return self.meta["on_get"]()

        if self.meta['type'] != 'composite':
            return self._current

        composite_val = {}
        for key in self.meta['composite_actions']:
            val = self.meta['composite_actions'][key].value.get_value()
            if val is None:
                # A sub-value in a composite can't be null, otherwise the entire
                # composite is invalid
                return None
            composite_val[key] = val
        return composite_val

    def get_value_for_mqtt_status_update(self):
        """ Prepares a map with this action's user changes, to be sync'd to MQTT """
        if not self._needs_mqtt_propagation:
            # log.debug(
            #    'No need to MQTT update this action in %s',
            #    self.thing_name)
            return None

        # log.debug('Will send MQTT update for %s', self.thing_name)
        self._needs_mqtt_propagation = False

        # Most value logic is in get_value, but bools are special: we need to send
        # back $value_on/$value_off instead of True/False, and the rest of the app
        # will expect True/False instead of a random string
        if self.meta['type'] == 'binary':
            return self.meta['value_on'] if self._current \
                else self.meta['value_off']

        return self.get_value()


def make_user_defined_zigbee2mqttaction(
        thing_name,
        name,
        description,
        setter=None,
        getter=None):
    """ Helper to make user-defined actions """
    if getter is None:
        def getter():
            return None
    return Zigbee2MqttAction(
        name=name,
        description=description,
        can_set=(setter is not None),
        can_get=(getter is not None),
        value=Zigbee2MqttActionValue(
            thing_name=thing_name,
            meta={
                'type': 'user_defined',
                'on_set': setter,
                'on_get': getter},
        ))


@dataclass(frozen=True)
class Zigbee2MqttAction:
    """
    Holds the immutable bits of Zigbee2MqttActionValue.
    See that class, it's more interesting.
    """
    name: str
    description: str
    can_set: bool
    can_get: bool
    value: Zigbee2MqttActionValue

    def dictify(self):
        """ Meta data on this thing's method """
        return {
            "name": self.name,
            "description": self.description,
            "can_set": self.can_set,
            "can_get": self.can_get,
            "value": self.value.dictify(),
        }

    def debug_str(self):
        """ Pretty print """
        mode = 'Bcast'
        if self.can_get and self.can_set:
            mode = 'RW'
        elif self.can_get:
            mode = 'R'
        elif self.can_set:
            mode = 'W'
        return f'\t{self.name} [{mode}], {self.description} = {self.value.debug_str()}'

    def accepts_value(self, key, val):
        """
        An action always accepts a value if it's immediate.
        A composite action needs to match the received value to accept it.
        """
        if key == self.name:
            return True

        if (self.value.meta['type'] == 'composite') and (
                self.value.meta['property'] == key):
            # Exclude IgnoredActions from expected keys
            expected_keys = set(
                k for k, v in self.value.meta['composite_actions'].items()
                if not isinstance(v, IgnoredAction))
            avail_keys = set(val.keys())
            return expected_keys.intersection(avail_keys) == expected_keys

        return False

    def set_value_from_mqtt_update(self, val):
        """
        Updates state from MQTT
        Note there's no need to check set-allowed bit, we're updating from an MQTT
        message and MQTT is the source of truth.
        """
        self.value.set_value_from_mqtt_update(val)

    def set_value(self, val):
        """
        Updates state from user, will set needs-propagation flag.
        Will throw if this action is read-only.
        """
        if not self.can_set and (self.value.meta['type'] != 'composite'):
            raise ValueError(
                f'Tried to set {self.name} to {val}, but action is read only')
        self.value.set_value(val)

    def get_value(self):
        """ Returns currently known value (which may be out of sync with MQTT) """
        if self.value.meta['type'] != 'composite':
            return {self.name: self.value.get_value()}

        if self.value.get_value() is None:
            return None
        return {self.value.meta['property']: self.value.get_value()}

    def make_mqtt_status_update(self):
        """
        Prepares a status-sync message for MQTT, only of changed fields.
        Clears the needs-propagation bit if set.
        """
        if not self.can_set and self.value.meta['type'] != 'composite':
            # log.debug(
            #    'Thing %s.%s can\'t be MQTT set, will send no update',
            #    self.value.thing_name,
            #    self.name)
            return {}

        val = self.value.get_value_for_mqtt_status_update()
        if val is None:
            # log.debug(
            #    'Thing %s.%s has value None, will send no update',
            #    self.value.thing_name,
            #    self.name)
            return {}

        name = self.name if self.value.meta['type'] != 'composite' else self.value.meta['property']
        # log.debug(
        #    'Thing %s.%s has update %s=%s',
        #    self.value.thing_name,
        #    self.name,
        #    name,
        #    val)
        return {name: val}


def _get_action_metadata(thing_name, action):
    meta = {'type': action['type']}

    if 'presets' in action:
        meta['presets'] = action['presets']

    if meta['type'] == 'binary':
        meta['value_off'] = action['value_off']
        meta['value_on'] = action['value_on']
        return meta

    if meta['type'] == 'numeric':
        meta['value_min'] = int(
            action['value_min']) if 'value_min' in action else None
        meta['value_max'] = int(
            action['value_max']) if 'value_max' in action else None
        return meta

    if meta['type'] == 'enum':
        meta['values'] = action['values']
        return meta

    if meta['type'] == 'composite':
        sub_acts = {}
        for sub_action in action['features']:
            sub_act = Zigbee2MqttAction(
                name=sub_action['property'],
                description=meta.get('description', ''),
                can_set=(int(sub_action.get('access', 0)) & 0b010 != 0),
                can_get=(int(sub_action.get('access', 0)) & 0b100 != 0),
                value=_build_zigbee2mqtt_action_value(thing_name, sub_action),
            )
            sub_acts[sub_act.name] = sub_act
        meta['composite_actions'] = sub_acts
        # property may not exist when parsing item_type of a list
        meta['property'] = action.get('property')
        return meta

    if meta['type'] == 'list':
        meta['item_type'] = action.get('item_type', {})
        meta['length_min'] = action.get('length_min')
        meta['length_max'] = action.get('length_max')
        # property may not exist when parsing item_type recursively
        meta['property'] = action.get('property')
        # Parse the item_type schema recursively for validation/debug purposes
        if meta['item_type']:
            meta['item_type_meta'] = _get_action_metadata(thing_name, meta['item_type'])
        return meta

    log.error('Thing %s has an unsuported action: %s', thing_name, action)
    return meta


def _build_zigbee2mqtt_action_value(thing_name, action):
    return Zigbee2MqttActionValue(
        thing_name=thing_name,
        meta=_get_action_metadata(thing_name, action),
    )


def _parse_zigbee2mqtt_action(thing_name, action):
    # Composite actions need to be refered to by their name, others by
    # property (most often they are the same)
    if action['type'] == 'composite':
        name = action['name']
    else:
        name = action['property']

    return Zigbee2MqttAction(
        name=name,
        description=action.get('description', ''),
        can_set=(int(action.get('access', 0)) & 0b010 != 0),
        can_get=(int(action.get('access', 0)) & 0b100 != 0),
        value=_build_zigbee2mqtt_action_value(thing_name, action),
    )


def _parse_zigbee2mqtt_actions(thing_name, definition):
    thing_type = None
    actions = {}
    for node in definition.get('exposes', []):
        if 'features' in node:
            maybe_thing_type = node.get('type', None)
            if thing_type is None:
                thing_type = maybe_thing_type
            elif maybe_thing_type is None or maybe_thing_type.lower() in ['composite']:
                # If feature has no type, ignore. If it's a composite, the type should be
                # defined by a higher level action (a composite means we're in a recursive call)
                pass
            else:
                log.warning(
                    'Thing "%s" type-heuristic multiple match: first match is %s, new match is %s. '
                    'Keeping type as first match.', thing_name, thing_type, maybe_thing_type)
            for act in node['features']:
                action = _parse_zigbee2mqtt_action(thing_name, act)
                actions[action.name] = action
        else:
            action = _parse_zigbee2mqtt_action(thing_name, node)
            actions[action.name] = action
    return thing_type, ActionDict(actions)


def parse_from_zigbee2mqtt(thing_id, thing, known_aliases=None):
    """
    Parses a message from zigbee2mqtt to create a local replica, with
    self-describing metadata.
    """
    known_aliases = known_aliases or {}
    addr = thing['ieee_address']
    real_name = thing.get('friendly_name', addr)  # Unaliased name
    name = known_aliases.get(real_name, known_aliases.get(addr, real_name))
    if real_name != name:
        log.info(
            'Thing %s is an alias for thing %s addr %s',
            name,
            real_name,
            addr)

    definition = thing.get('definition', {}) or {}
    model_id = thing.get('model_id', None)
    model = definition.get('model', model_id)
    thing_type, actions = _parse_zigbee2mqtt_actions(name, definition)
    return Zigbee2MqttThing(
        thing_id=thing_id,
        address=addr,
        name=name,
        real_name=real_name,
        broken=(not thing['interview_completed']) and (not thing['interviewing']),
        manufacturer=thing.get('manufacturer', None),
        model=model,
        description=definition.get('description', None),
        thing_type=thing_type,
        actions=actions,
        extras=ThingExtras(name),
    )


def create_virtual_thing(name, description, thing_type, manufacturer):
    """Create a virtual thing (non-zigbee) that can be registered with Z2MProxy.

    Virtual things have no zigbee actions - all their values are stored in extras.
    They can be used for external data sources like weather APIs.

    Args:
        name: Unique name for the thing
        description: Optional description
        thing_type: Optional type (e.g., 'sensor', 'weather')
        manufacturer: Optional manufacturer/source name

    Returns:
        A Zigbee2MqttThing with is_zigbee_mqtt=False
    """
    return Zigbee2MqttThing(
        thing_id=-1,  # Virtual things don't have zigbee IDs
        address=f'virtual:{name}',
        name=name,
        real_name=name,
        broken=False,
        manufacturer=manufacturer,
        model=None,
        description=description,
        thing_type=thing_type,
        actions=ActionDict(),
        extras=ThingExtras(name),
        is_zigbee_mqtt=False,
    )
