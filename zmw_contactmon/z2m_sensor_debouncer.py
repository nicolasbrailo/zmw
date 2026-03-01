from collections import deque
from datetime import datetime

from zzmw_lib.logs import build_logger
from zzmw_lib.z2m.z2mproxy import Z2MProxy

log = build_logger("Z2mContactSensorDebouncer")

class Z2mContactSensorDebouncer:
    """
    Debounces sensor reports: a CB will only trigger when a report sensor is 'good': will skip duplicated reports,
    skip non-monitored sensors, validate sensor state, etc.
    """
    def __init__(self, cfg, mqtt, actions_on_sensor_change, cb_on_transition, scheduler):
        self.monitoring = {} # Things we're monitoring
        self.history = {} # History of things we're monitoring
        self.monitoring_prev_state = {} # Last known contact state for each thing
        self.cb_on_transition = cb_on_transition
        self._actions_on_sensor_change = actions_on_sensor_change
        self._z2m = Z2MProxy(cfg, mqtt, scheduler,
                             cb_on_z2m_network_discovery=self._on_z2m_network,
                             cb_is_device_interesting=lambda t: 'contact' in t.actions.keys())

    def get_sensors_state(self):
        """ Return most recent state for each sensor as known by this service """
        stat = {}
        for k,v in self.history.items():
            if len(v) > 0:
                stat[k] = v[-1]
            else:
                stat[k] = {}
        return stat

    def get_contact_history(self):
        """ Return all of the transitions for each sensor seen by this service """
        # Flatten deques from history into lists, so they are json-serializable
        return {k:list(v) for k,v in self.history.items()}

    def _on_z2m_network(self, _is_first_discovery, known_things):
        monitoring = {}
        log.info("Z2M network published, there are %d things that look like contact sensors", len(known_things))
        contacts = self._z2m.get_all_registered_things()
        for thing in contacts:
            monitoring[thing.name] = thing
            log.info("%s looks like a contact sensor, will monitor", thing.name)
            thing.on_any_change_from_mqtt = self._on_contact_change
            if thing.name not in self.history:
                self.history[thing.name] = deque(maxlen=10)
        self.monitoring = monitoring

    def _on_contact_change(self, thing):
        if thing.name not in self.monitoring:
            # This shouldn't happen, a cb shouldn't be installed if we're not monitoring this thing
            log.error("Received event for '%s', but sensor is not being monitored", thing.name)
            return

        now_contact = self.monitoring[thing.name].get('contact')
        prev_contact_state = self.monitoring_prev_state.get(thing.name, None)
        self.monitoring_prev_state[thing.name] = now_contact
        self._record_history(thing, now_contact, prev_contact_state)

        if thing.name not in self._actions_on_sensor_change:
            log.debug("Sensor %s reports contact=%s. No actions for this sensor", thing.name, now_contact)
            return

        if now_contact not in [True, False]:
            log.error("Received event for '%s', but sensor state is unknown (not 'open' or 'closed')", thing.name)
            return

        normal_state = self._actions_on_sensor_change[thing.name]['normal_state']
        entering_non_normal = now_contact != normal_state
        action = 'open' if entering_non_normal else 'close'

        has_act = action in self._actions_on_sensor_change[thing.name]
        has_to = 'timeout' in self._actions_on_sensor_change[thing.name]
        if not has_act and not has_to:
            log.debug("Sensor %s reports contact=%s. No actions for this this transition", thing.name, now_contact)
            return

        # If this is the first report for this sensor, prev_contact will be None and now_contact will be True or False
        # This means if now_contact == prev_contact, ignore (it's a repeated announce, the sensor hasn't changed)
        if now_contact == prev_contact_state:
            log.debug("Sensor %s reports contact=%s - no state change, ignoring", thing.name, now_contact)
            return

        if prev_contact_state is None and not entering_non_normal:
            log.debug("Will ignore first report for sensor %s", thing.name)
            return

        if prev_contact_state is None and entering_non_normal:
            log.info("1st report for %s reports active. Will assume sensor fired.", thing.name)
            # If we got a first report from a sensor, and the sensor transitioned to non-normal it is likely
            # to be a 'real' (not a periodic) report. This means we should assume the sensor fired (better to have
            # a false-trigger than possibly ignoring the first state transition)
            prev_contact_state = normal_state

        self.cb_on_transition(thing, now_contact, action, prev_contact_state, entering_non_normal)


    def _record_history(self, thing, now_contact, prev_contact_state):
        if now_contact == prev_contact_state:
            # Debounce history. This isn't done as part of the normal _on_contact_change, as we may be recording
            # history for sensors without configuration, and the config may change these events
            return
        try:
            normal_state = self._actions_on_sensor_change[thing.name]['normal_state']
        except KeyError:
            # We may receive reports for sensors we're not monitoring. For those, assume an arbitrary normal_state
            # Worst case scenario, we'll get the history "flipped" (ie mark close when it's open) but since they have no
            # actions, it's a benign problem
            normal_state = True

        entering_non_normal = now_contact != normal_state
        action = 'open' if entering_non_normal else 'close'
        last_state = {
                'contact': now_contact,
                'in_normal_state': not entering_non_normal,
                'action': action,
                'changed': datetime.now(),
        }
        self.history[thing.name].append(last_state)
