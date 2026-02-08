"""Heating rules for MQTT-based temperature control."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, time

from schedule import AllowOn

from zzmw_lib.logs import build_logger
log = build_logger("HeatingRules")


# T below this will be assumed to be a reading error
MIN_REASONABLE_T = -5
# T above this will be assumed to be a reading error and ignored
MAX_REASONABLE_T = 45

def safe_read_sensor(zmw, sensor, metric):
    """Read sensor metric, return None if unavailable or invalid."""
    if zmw is None:
        log.debug("Attempted to read sensor %s, but z2m not set yet", sensor)
        return None

    try:
        thing = zmw.get_thing(sensor)
    except KeyError:
        log.debug("Sensor %s is not known, ignoring this tick().", sensor)
        return None

    # Try reading from thing.actions first
    if metric in thing.actions:
        val = thing.get(metric)
    elif metric in thing.extras:
        val = thing.extras.get(metric)
    else:
        log.debug("Sensor %s isn't monitoring %s, ignoring this tick()", sensor, metric)
        return None

    try:
        float(val)
    except (ValueError, TypeError):
        log.debug("Sensor %s returned %s=%s, which isn't a number. Ignoring.", sensor, metric, val)
        return None

    val = float(val)
    if val > MAX_REASONABLE_T:
        log.debug(
            "Sensor %s returned %s=%s, which is probably a reading error "
            "(expected less than %s). Ignoring.",
            sensor, metric, val, MAX_REASONABLE_T)
        return None
    if val < MIN_REASONABLE_T:
        log.debug(
            "Sensor %s returned %s=%s, which is probably a reading error "
            "(expected less than %s). Ignoring.",
            sensor, metric, val, MIN_REASONABLE_T)
        return None

    return val

class MqttHeatingRule(ABC):
    @abstractmethod
    def set_z2m(self, _z2m):
        """Set the zigbee2mqtt reference."""

    @abstractmethod
    def apply(self, _sched):
        """Apply this rule to the schedule."""

    @abstractmethod
    def get_monitored_sensors(self):
        """Return dict of monitored sensors and their values."""

    def set_boiler_state_cb(self, _get_state_cb):
        """Set callback to query actual boiler state. Returns True if on."""
        pass  # default no-op for rules that don't need it

class DefaultOff(MqttHeatingRule):
    REASON = "No reason to turn on"
    def __init__(self, _cfg):
        log.info("Will use rule DefaultOff")
    def set_z2m(self, _z2m):
        return True
    def apply(self, sched):
        sched.set_now_from_rule(False, DefaultOff.REASON)
    def get_monitored_sensors(self):
        return {}


class DefaultOn(MqttHeatingRule):
    REASON = "Configured always on"
    def __init__(self, _cfg):
        log.info("Will use rule DefaultOn")
    def set_z2m(self, _z2m):
        return True
    def apply(self, sched):
        sched.set_now_from_rule(True, DefaultOff.REASON)
    def get_monitored_sensors(self):
        return {}

class CheckTempsWithinRange(MqttHeatingRule):
    """ Failsafe rule: will shut down/turn on if temp sensors are not within a normal range """

    def __init__(self, cfg):
        self._zmw = None
        self.min_t_delta = 10  # Min diff between user set max and user set min
        self.min_temp = cfg['min_temp']
        self.max_temp = cfg['max_temp']
        self.sensors_to_monitor = cfg['sensors']
        self.metric = cfg['metric']

        if not isinstance(self.min_temp, int) or not isinstance(self.max_temp, int):
            raise ValueError("Config error: min and max temp must be ints")

        if self.min_temp > self.max_temp:
            raise ValueError(
                f"Requested max temp ({self.max_temp}) is less than "
                f"min temp ({self.min_temp})")

        if self.max_temp - self.min_temp < self.min_t_delta:
            raise ValueError(
                f"Requested difference between max and min temp is less than "
                f"{self.min_t_delta} ({self.max_temp} and {self.min_temp})")

        log.info("Will use rule CheckTempsWithinRange, monitoring sensors [%s] to", ", ".join(self.sensors_to_monitor))
        log.info("\t- turn off if temp > %d", self.max_temp)
        log.info("\t- turn on if temp < %d", self.min_temp)

    def get_monitored_sensors(self):
        return {s: safe_read_sensor(self._zmw, s, self.metric) for s in self.sensors_to_monitor}

    def set_z2m(self, z2m):
        self._zmw = z2m
        found_all = True
        for s in self.sensors_to_monitor:
            try:
                # Verify all sensors we expect are in the network
                z2m.get_thing(s)
            except KeyError:
                log.error("Rule CheckTempsWithinRange expects sensor '%s', but it's missing from the network", s)
                found_all = False
        return found_all

    def apply(self, sched):
        more_than_max = []
        less_than_min = []
        for sensor in self.sensors_to_monitor:
            temp = safe_read_sensor(self._zmw, sensor, self.metric)
            if temp is None:
                continue
            if temp > self.max_temp:
                more_than_max.append((sensor, temp))
            if temp < self.min_temp:
                less_than_min.append((sensor, temp))

        if len(more_than_max) > 0 and len(less_than_min) > 0:
            log.error(
                "Found sensors above temp limit, and also sensors below temp limit. "
                "Skipping this rule, heating state can't be set.")
            log.error(
                "Sensors above temp limit (%s): %s",
                self.max_temp, ', '.join([f"{n} ({t})" for n, t in more_than_max]))
            log.error(
                "Sensors below temp limit (%s): %s",
                self.min_temp, ', '.join([f"{n} ({t})" for n, t in less_than_min]))
        elif len(more_than_max) > 0:
            reason = (f"Sensor above {self.max_temp}C: " +
                      ', '.join([f"{n} ({t})" for n, t in more_than_max]))
            log.info("Request heating off: %s", reason)
            sched.set_now_from_rule(False, reason)
        elif len(less_than_min) > 0:
            reason = (f"Sensor below {self.min_temp}C: " +
                      ', '.join([f"{n} ({t})" for n, t in less_than_min]))
            log.info("Request heating on: %s", reason)
            sched.set_now_from_rule(True, reason)


class ScheduledMinTargetTemp(MqttHeatingRule):
    @dataclass(frozen=True)
    class SensorTimeSchedule:
        sensor_name: str
        start_time: time
        end_time: time
        days: str
        target_min_temp: int
        target_max_temp: int

        def is_active(self, t):
            """Check if schedule is active at given time."""
            if self.start_time <= t.time() <= self.end_time:
                if self.days == 'all':
                    return True
                if self.days == 'week':
                    return t.weekday() < 5
                if self.days == 'weekend':
                    return t.weekday() in [5, 6]
                log.error("Unexpected days in schedule: %s", self.days)
                return True
            return False

        @staticmethod
        def guess_days(val):
            """Validate and return days value."""
            supported = ['all', 'week', 'weekend']
            if val in supported:
                return val
            raise ValueError(
                f"SensorTimeSchedule days '{val}' not supported. Expected: {supported}")

        @staticmethod
        def create_from_json_obj(sensor_name, sched):
            """Parse a single schedule entry from JSON."""
            try:
                st = ScheduledMinTargetTemp.SensorTimeSchedule(
                    sensor_name=sensor_name,
                    start_time=datetime.strptime(sched['start'], "%H:%M").time(),
                    end_time=datetime.strptime(sched['end'], "%H:%M").time(),
                    target_min_temp=float(sched['target_min_temp']),
                    target_max_temp=float(sched['target_max_temp']),
                    days=ScheduledMinTargetTemp.SensorTimeSchedule.guess_days(
                        sched['days']))
                if (st.target_max_temp > MAX_REASONABLE_T or
                        st.target_max_temp < MIN_REASONABLE_T):
                    raise ValueError(
                        f"target_max_temp max temperature for sensor {sensor_name} set to {st.target_max_temp}, "
                        "which looks out or range for temperature ({MIN_REASONABLE_T} < t < {MAX_REASONABLE_T})")
                if (st.target_min_temp > MAX_REASONABLE_T or
                        st.target_min_temp < MIN_REASONABLE_T):
                    raise ValueError(
                        f"target_min_temp for sensor {sensor_name} set to {st.target_min_temp}, "
                        "which looks out or range for temperature ({MIN_REASONABLE_T} < t < {MAX_REASONABLE_T})")
                if st.target_min_temp > st.target_max_temp:
                    raise ValueError(
                        f"target_min_temp is higher than max temp for sensor {sensor_name} "
                        "({st.target_min_temp} < {st.target_max_temp})")
                return st
            except (ValueError, TypeError, KeyError):
                log.error("Failed to parse SensorTimeSchedule for sensor %s", sensor_name, exc_info=True)
                raise

    def __init__(self, rule, clock=None):
        self._clock = clock
        if self._clock is None:
            self._clock = datetime
        self._zmw = None
        self._is_active = False

        self.sensor_name = rule['sensor']
        self.metric = rule['metric']
        self.schedule = ScheduledMinTargetTemp.SensorTimeSchedule.create_from_json_obj(
            self.sensor_name, rule)

        log.info("Will use rule ScheduledMinTargetTemp on sensor %s:", self.sensor_name)
        log.info("\t %s-%s (%s): target temp %s-%s",
                 self.schedule.start_time.strftime("%H:%M"),
                 self.schedule.end_time.strftime("%H:%M"),
                 self.schedule.days,
                 self.schedule.target_min_temp,
                 self.schedule.target_max_temp)

    def get_monitored_sensors(self):
        return {self.sensor_name: safe_read_sensor(self._zmw, self.sensor_name, self.metric)}

    def set_z2m(self, z2m):
        self._zmw = z2m
        try:
            z2m.get_thing(self.sensor_name)
            return True
        except KeyError:
            log.error(
                "Rule ScheduledMinTargetTemp expects sensor '%s', "
                "but it's missing from the network", self.sensor_name)
            return False

    def apply(self, todaysched):
        if todaysched.get_now_slot().allow_on != AllowOn.RULE:
            # This specific rule is only for scheduled slots, but we may be running
            # rules during non scheduled slots (eg when getting a user boost, we
            # still want to check other rules like maximum or minimum temps). If we're running this rule during a non-schedule slot,
            # just ignore it
            return

        sched = self.schedule
        if not sched.is_active(self._clock.now()):
            # Schedule not active. Check if we need to report deactivation.
            if self._is_active:
                self._is_active = False
                if not todaysched.get_now_slot().request_on:
                    reason = (f"Schedule for {self.sensor_name} finished at "
                              f"{sched.end_time} and is no longer active")
                    log.info("ScheduledMinTargetTemp rule stopped applying: %s", reason)
                    todaysched.set_now_from_rule(False, reason)
            return

        temp = safe_read_sensor(self._zmw, self.sensor_name, self.metric)

        if temp is None and not self._is_active:
            # This sensor is not responding, ignore its rules
            return
        if temp is None and self._is_active:
            reason = (f"Sensor {self.sensor_name} stopped responding with an "
                      f"active rule. Heating will remain on until rule expires "
                      f"at {sched.end_time}, or sensor updates.")
            log.error(reason)
            todaysched.set_now_from_rule(True, reason)
            return

        if (temp < sched.target_min_temp or
                (self._is_active and temp < sched.target_max_temp)):
            reason = (f"Sensor {self.sensor_name} reports {temp}C, target is "
                      f"{sched.target_max_temp}C between {sched.start_time} "
                      f"and {sched.end_time}")
            log.info("Request heating on by ScheduledMinTargetTemp: %s", reason)
            todaysched.set_now_from_rule(True, reason)
            self._is_active = True
            return

        # Schedule is active but temp is above threshold
        if self._is_active:
            self._is_active = False
            if not todaysched.get_now_slot().request_on:
                reason = (f"Sensor {self.sensor_name} reports above target "
                          f"temperature of {sched.target_max_temp}C")
                log.info("ScheduledMinTargetTemp rule stopped applying: %s", reason)
                todaysched.set_now_from_rule(False, reason)


def create_rules_from_config(rules_cfg):
    """Instantiate rules from config list."""
    from rules_predictive_target_temp import PredictiveTargetTemperature
    known_rules = [DefaultOff, CheckTempsWithinRange, ScheduledMinTargetTemp, PredictiveTargetTemperature]

    def _get_rule_class(name):
        for cls in known_rules:
            if cls.__name__ == name:
                return cls
        return None

    rules = []
    for rule in rules_cfg:
        cls = _get_rule_class(rule['name'])
        if cls:
            try:
                rules.append(cls(rule))
            except Exception as ex:
                raise ValueError(f"Failed to setup heating schedule rule {rule['name']}") from ex
        else:
            raise ValueError(f"Failed to setup heating schedule, requested unknown rule {rule['name']}")
    return rules
