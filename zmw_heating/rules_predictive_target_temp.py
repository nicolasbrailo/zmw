"""Predictive heating rule to reach target temperature by a specific time."""
from datetime import datetime, time

from rules import MqttHeatingRule, safe_read_sensor, MIN_REASONABLE_T, MAX_REASONABLE_T
from zzmw_lib.logs import build_logger

log = build_logger("PredictiveTargetTemperature")


def _guess_days(val):
    """Validate and return days value."""
    supported = ['all', 'week', 'weekend']
    if val in supported:
        return val
    raise ValueError(
        f"PredictiveTargetTemperature days '{val}' not supported. Expected: {supported}")


class PredictiveTargetTemperature(MqttHeatingRule):
    """Rule that predicts when to start heating to reach target temperature by a specific time."""

    def __init__(self, cfg, clock=None):
        self._clock = clock
        if self._clock is None:
            self._clock = datetime
        self._zmw = None
        self._get_boiler_state = None

        self.sensor_name = cfg['sensor']
        self.metric = cfg['metric']
        self.target_time = datetime.strptime(cfg['target_time'], "%H:%M").time()
        self.start_time = datetime.strptime(cfg['start'], "%H:%M").time()
        self.days = _guess_days(cfg['days'])
        self.target_min_temp = float(cfg['target_min_temp'])
        self.target_max_temp = float(cfg['target_max_temp'])

        if (self.target_max_temp > MAX_REASONABLE_T or
                self.target_max_temp < MIN_REASONABLE_T):
            raise ValueError(
                f"target_max_temp for sensor {self.sensor_name} set to {self.target_max_temp}, "
                f"which looks out of range for temperature ({MIN_REASONABLE_T} < t < {MAX_REASONABLE_T})")
        if (self.target_min_temp > MAX_REASONABLE_T or
                self.target_min_temp < MIN_REASONABLE_T):
            raise ValueError(
                f"target_min_temp for sensor {self.sensor_name} set to {self.target_min_temp}, "
                f"which looks out of range for temperature ({MIN_REASONABLE_T} < t < {MAX_REASONABLE_T})")
        if self.target_min_temp > self.target_max_temp:
            raise ValueError(
                f"target_min_temp is higher than max temp for sensor {self.sensor_name} "
                f"({self.target_min_temp} > {self.target_max_temp})")

        log.info("Will use rule PredictiveTargetTemperature on sensor %s:", self.sensor_name)
        log.info("\t target %s-%sC by %s (starting from %s, %s)",
                 self.target_min_temp,
                 self.target_max_temp,
                 self.target_time.strftime("%H:%M"),
                 self.start_time.strftime("%H:%M"),
                 self.days)

    def get_monitored_sensors(self):
        return {self.sensor_name: safe_read_sensor(self._zmw, self.sensor_name, self.metric)}

    def set_z2m(self, z2m):
        self._zmw = z2m
        for sn in [self.sensor_name, "Weather"]:
            try:
                z2m.get_thing(sn)
            except KeyError:
                log.error(
                    "Rule PredictiveTargetTemperature expects sensor '%s', "
                    "but it's missing from the network", sn)
                return False

    def set_boiler_state_cb(self, get_state_cb):
        """Set callback to query actual boiler state. Returns True if on."""
        self._get_boiler_state = get_state_cb

    def apply(self, todaysched):
        # TODO: Implement predictive heating logic
        pass
