from zzmw_lib.geo_helpers import is_sun_out
import threading
import time

from zz2m.z2mproxy import Z2MProxy
from zzmw_lib.logs import build_logger

log = build_logger("DoorOpenScene")

class DoorOpenSceneLightManager:
    def __init__(self, cfg, mqtt_client, scheduler):
        self._wanted_things = cfg["door_open_scene_thing_to_manage"]
        self._known_things = {}
        self._managing_things = {}
        self._managing_things_lock = threading.Lock()
        self._ignoring_updates_until = None
        self._ignore_updates_secs = 3
        self._is_running = False
        self._z2m = Z2MProxy(cfg, mqtt_client, scheduler,
                             cb_on_z2m_network_discovery=self._on_z2m_network_discovery,
                             cb_is_device_interesting=lambda t: t.name in self._wanted_things)

    def _on_z2m_network_discovery(self, _is_first_discovery, known_things):
        log.info("Z2M network discovered, monitoring %d things: %s", len(known_things), list(known_things.keys()))
        for thing_name in self._wanted_things:
            if thing_name not in known_things:
                log.error("Thing %s missing, door-open scene may not work as expected", thing_name)

        for _, thing in known_things.items():
            if thing.thing_type != 'light':
                log.error("Asked to monitor %s for door-open scene, but it's not a light", thing.name)
            else:
                self._known_things[thing.name] = thing
                thing.on_any_change_from_mqtt = lambda t=thing: self._light_received_mqtt_update(t)

    def _light_received_mqtt_update(self, thing):
        with self._managing_things_lock:
            if thing.name not in self._managing_things:
                return
            if self._ignoring_updates_until is not None and time.time() < self._ignoring_updates_until:
                # When the light is turned on, we're going to get callbacks here. There is no way to distinguish
                # an external update from an update triggered by an internal sync.
                return
            del self._managing_things[thing.name]
        log.info("Thing %s is not managed anymore, something else started using it", thing.name)

    def start(self):
        """ Starts the door-open scene: it will turn on all of the managed lights, until stop() is called. If other
        service starts making use of this light, it will stop being managed (we will ignore it during the stop()
        phase. Calling start() multiple times is a noop. """
        if self._is_running:
            return
        self._is_running = True
        for _, thing in self._known_things.items():
            if thing.is_light_on():
                log.info("Won't apply door-open scene to %s, something else is using this light", thing.name)
                continue
            thing.turn_on()
            self._managing_things[thing.name] = thing
        self._ignoring_updates_until = time.time() + self._ignore_updates_secs
        self._z2m.broadcast_things(self._managing_things.keys())

    def stop(self):
        """ Stop scene: all lights that are still managed will be shut down """
        log.info("Door-open scene expired, turn off lights")
        with self._managing_things_lock:
            self._is_running = False
            # Ignore self-updates for a few secs
            self._ignoring_updates_until = time.time() + self._ignore_updates_secs
            for _, thing in self._managing_things.items():
                log.info("Door-open scene timeout, shutdown %s", thing.name)
                thing.turn_off()
            self._z2m.broadcast_things(self._managing_things.keys())
            self._managing_things = {}

class DoorOpenScene:
    def __init__(self, cfg, mqtt_client, scheduler):
        self._light_mgr = DoorOpenSceneLightManager(cfg, mqtt_client, scheduler)
        self._door_open_scene_timer = None
        self._door_open_scene_timeout_secs = cfg["door_open_scene_timeout_secs"]
        self._latlon = cfg["latlon"]
        _ = is_sun_out(self._latlon[0], self._latlon[1])

    def maybe_start(self):
        """ Door has opened, check if we need to launch a door-open scene or not """
        if is_sun_out(self._latlon[0], self._latlon[1]):
            log.debug("DoorOpenScene won't start, there is enough light outside")
            return

        if self._door_open_scene_timer is not None:
            self.pet_timer()
            return

        log.debug("DoorOpenScene starting, it is dark outside")
        self._door_open_scene_timer = threading.Timer(
            self._door_open_scene_timeout_secs,
            self._on_door_open_scene_timeout
        )
        self._door_open_scene_timer.start()
        self._light_mgr.start()

    def pet_timer(self):
        """ Something happened that should extend the door-open scene """
        if self._door_open_scene_timer is None:
            # Trying to reset timer, but no timer is active
            return
        self._door_open_scene_timer.cancel()
        log.debug("DoorOpenScene timeout has been extended")
        self._door_open_scene_timer = threading.Timer(
            self._door_open_scene_timeout_secs,
            self._on_door_open_scene_timeout
        )
        self._door_open_scene_timer.start()

    def _on_door_open_scene_timeout(self):
        """ Called when the door-open scene timer expires """
        self._door_open_scene_timer = None
        self._light_mgr.stop()
