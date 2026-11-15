""" Connection to one Roomba (and discovery of its IP), over the robot's local MQTT API via roombapy """
import asyncio
import copy
import logging
import time

from roombapy import RoombaClient, RoombaAuthError, RoombaDiscovery, ROOMBA_STATES

from zzmw_lib.logs import build_logger

log = build_logger("ZmwSucksRoomba")
logging.getLogger("roombapy").setLevel(logging.WARNING)

# How long to wait before retrying when a robot can't be found or connected to
_CONNECT_RETRY_SECS = 30
# Once connected, roombapy reconnects by itself, but always to the same IP. If a robot (without a fixed ip in
# config) stays disconnected this long, assume its IP changed: drop the connection and rediscover it.
_REDISCOVER_AFTER_DISCONNECTED_SECS = 5 * 60
# How often to check the connection state of a connected robot
_CONNECTION_CHECK_SECS = 30
# How long to listen for replies to a discovery broadcast
_DISCOVERY_WINDOW_SECS = 5
# How often to ask a robot for its position, while it's away from the dock. Not every firmware supports position
# requests: after this many unanswered requests in a row, stop asking until the next connection.
_POSITION_POLL_SECS = 5
_POSITION_MAX_TIMEOUTS = 3

# cleanSchedule2 day numbers
SCHEDULE_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# Settings that can be changed with set_setting, and their valid values. Each maps to a set of robot preferences
# that must be sent together (the firmware ignores half of a group, see roombapy's set_preferences)
SETTINGS = {
    "passes": ["auto", "one", "two"],
    "bin_pause": ["true", "false"],
    "child_lock": ["true", "false"],
}


def _setting_to_prefs(setting, value):
    match setting:
        case "passes":
            return {"noAutoPasses": value != "auto", "twoPass": value == "two"}
        case "bin_pause":
            return {"binPause": value == "true"}
        case "child_lock":
            return {"childLock": value == "true"}
    raise KeyError(setting)


def _parse_schedule(reported):
    """ cleanSchedule2 (i/s series) to something readable. Robots with the older cleanSchedule aren't supported """
    entries = []
    for entry in reported.get("cleanSchedule2") or []:
        start = entry.get("start", {})
        days = start.get("day") or []
        entries.append({
            "enabled": bool(entry.get("enabled")),
            "days": [SCHEDULE_DAYS[d] for d in days if 0 <= d < len(SCHEDULE_DAYS)],
            "day_nums": days,
            "hour": start.get("hour"),
            "min": start.get("min"),
            "command": entry.get("cmd", {}).get("command"),
        })
    return {
        "paused": bool(reported.get("schedHold")),
        "timezone": reported.get("timezone"),
        "entries": entries,
    }


class Discovery:
    """ Finds robots' IPs by BLID, with a UDP broadcast. Shared by all robots: discovery binds a fixed port, so only
    one can run at a time. Each run learns the IPs of all robots that answer. """
    def __init__(self):
        # asyncio.Lock binds to the running loop on first use, so it's safe to create it out of the loop
        self._lock = asyncio.Lock()
        self._known_ips = {}

    async def find_ip(self, blid):
        """ IP of the robot with this BLID, or None if it didn't answer """
        async with self._lock:
            discovery = RoombaDiscovery()
            try:
                robots = await discovery.get_all(timeout=_DISCOVERY_WINDOW_SECS)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                log.warning("Roomba discovery failed: %s", ex)
                robots = []
            finally:
                await discovery.aclose()

            for robot in robots:
                if self._known_ips.get(robot.blid) != robot.ip:
                    log.info("Discovered Roomba %s (%s) at %s", robot.blid, robot.robot_name, robot.ip)
                self._known_ips[robot.blid] = robot.ip
            found_blids = {robot.blid for robot in robots}
            return self._known_ips.get(blid) if blid in found_blids else None


class Roomba:
    """ One robot. All robots share the service's asyncio loop """
    def __init__(self, loop, discovery, dev_cfg, on_state_change):
        self.alias = dev_cfg["alias"]
        self._fixed_ip = dev_cfg.get("ip")
        self._blid = dev_cfg["blid"]
        self._password = dev_cfg["password"]
        self._loop = loop
        self._discovery = discovery
        self._on_state_change = on_state_change
        self._ip = None
        self._client = None
        self._last_bcast_state = None
        self._disconnected_since = time.monotonic()
        self.auth_rejected = False
        # Last discovery didn't find the robot
        self.not_found = False
        # Last known position, and whether this robot answers position requests (None until we know)
        self._position = None
        self._position_supported = None
        self._task = asyncio.run_coroutine_threadsafe(self._run(), self._loop)

    async def _run(self):
        while True:
            self._ip = self._fixed_ip or await self._discovery.find_ip(self._blid)
            if self._ip is None:
                # Only log the first time: an offline robot would spam the log. It's a service alert meanwhile.
                if not self.not_found:
                    log.warning("%s (%s) not found on network, will keep retrying every %d secs",
                                self.alias, self._blid, _CONNECT_RETRY_SECS)
                self.not_found = True
                await asyncio.sleep(_CONNECT_RETRY_SECS)
                continue
            if self.not_found:
                log.info("%s (%s) found on network", self.alias, self._blid)
            self.not_found = False

            # RoombaClient must be created inside the loop that will run it
            self._client = RoombaClient(self._ip, self._blid, self._password)
            self._client.register_on_message_callback(lambda _msg: self._maybe_bcast_state())
            self._client.register_on_connection_state_callback(self._on_connection_state)
            try:
                await self._client.connect()
                log.info("Connected to %s at %s", self.alias, self._ip)
            except RoombaAuthError:
                log.error("%s at %s rejected credentials, won't retry", self.alias, self._ip)
                self.auth_rejected = True
                return
            except Exception as ex:  # pylint: disable=broad-exception-caught
                # Not just RoombaConnectionError: a bad config (eg unresolvable ip) shouldn't kill this robot forever
                log.warning("Can't connect to %s at %s (%s), retry in %d secs",
                            self.alias, self._ip, ex, _CONNECT_RETRY_SECS)
                await asyncio.sleep(_CONNECT_RETRY_SECS)
                continue

            # A firmware update comes with a reconnect, and may add position support
            self._position_supported = None
            position_task = asyncio.create_task(self._poll_position())
            try:
                if not await self._wait_until_lost():
                    return
            finally:
                position_task.cancel()
            log.warning("%s disconnected from %s for over %d secs, will rediscover it",
                        self.alias, self._ip, _REDISCOVER_AFTER_DISCONNECTED_SECS)
            await self._client.disconnect()

    async def _wait_until_lost(self):
        """ Returns False if the robot rejected our credentials (no point retrying), or True if the connection
        has been down long enough that the robot should be rediscovered. Never returns for a fixed ip robot,
        roombapy keeps reconnecting to it. """
        disconnected_since = None
        while True:
            await asyncio.sleep(_CONNECTION_CHECK_SECS)
            if self._client.auth_error is not None:
                log.error("%s at %s rejected credentials, won't retry", self.alias, self._ip)
                self.auth_rejected = True
                return False
            if self._client.connected or self._fixed_ip:
                disconnected_since = None
                continue
            if disconnected_since is None:
                disconnected_since = time.monotonic()
            elif time.monotonic() - disconnected_since > _REDISCOVER_AFTER_DISCONNECTED_SECS:
                return True

    async def _poll_position(self):
        timeouts = 0
        while True:
            await asyncio.sleep(_POSITION_POLL_SECS)
            if self._position_supported is False or not self._client.connected:
                continue
            if self._client.current_state == ROOMBA_STATES["charge"]:
                # Docked, position won't change. Asking could also keep the robot from sleeping.
                continue
            try:
                pos = await self._client.get_position()
            except TimeoutError:
                timeouts += 1
                if timeouts >= _POSITION_MAX_TIMEOUTS and not self._position_supported:
                    log.info("%s doesn't answer position requests, won't ask again until reconnected",
                             self.alias)
                    self._position_supported = False
                    self._maybe_bcast_state()
                continue
            except Exception as ex:  # pylint: disable=broad-exception-caught
                log.debug("%s position request failed: %s", self.alias, ex)
                continue
            timeouts = 0
            self._position_supported = True
            if pos is not None:
                # None means the robot answered, but has no fix: keep the last known position
                # Rounded (and no timestamp) so a robot standing still doesn't trigger a state announcement
                self._position = {"x_m": round(pos.x, 2), "y_m": round(pos.y, 2), "theta_rad": round(pos.theta, 2)}
            self._maybe_bcast_state()

    def _on_connection_state(self, state, error):
        if state == "connected":
            self._disconnected_since = None
        elif self._disconnected_since is None:
            self._disconnected_since = time.monotonic()
        if error:
            log.warning("%s connection %s: %s", self.alias, state, error)
        else:
            log.info("%s connection %s", self.alias, state)
        self._maybe_bcast_state()

    def disconnected_for_secs(self):
        """ How long the robot has been disconnected (since service start, if it never connected). 0 if connected """
        since = self._disconnected_since
        return 0 if since is None else time.monotonic() - since

    def get_state(self):
        """ State of this robot, as announced over MQTT """
        if self._client is None or not self._client.connected:
            return {"alias": self.alias, "connected": False}
        reported = self._client.reported
        mission = reported.get("cleanMissionStatus", {})
        run_stats = reported.get("bbrun", {})
        mission_stats = reported.get("bbmssn", {})
        bat_info = reported.get("batInfo", {})
        charge_stats = reported.get("bbchg3", {})
        signal = reported.get("signal", {})
        error_code = self._client.error_code
        has_error = error_code not in (None, 0)
        if not reported.get("noAutoPasses"):
            passes = "auto"
        else:
            passes = "two" if reported.get("twoPass") else "one"
        return {
            "alias": self.alias,
            "connected": True,
            "ip": self._ip,
            "robot_name": reported.get("name"),
            "state": self._client.current_state,
            "phase": self._client.cleanMissionStatus_phase,
            "battery_pct": reported.get("batPct"),
            "bin_full": self._client.bin_full,
            "error_code": error_code if has_error else None,
            "error": self._client.error_message if has_error else None,
            "mission": {
                "id": mission.get("missionId"),
                "cycle": mission.get("cycle"),
                "initiator": mission.get("initiator"),
                "start_time": mission.get("mssnStrtTm"),
                "minutes": mission.get("mssnM"),
                "sqft": mission.get("sqft"),
                "recharge_minutes": mission.get("rechrgM"),
                "expire_minutes": mission.get("expireM"),
            },
            "lifetime": {
                "runtime_hours": run_stats.get("hr"),
                "runtime_minutes": run_stats.get("min"),
                # Lifetime area is reported in hundreds of sqft (an i1 reported 494 after 334 hours of cleaning)
                "sqft": run_stats["sqft"] * 100 if run_stats.get("sqft") is not None else None,
                "missions": mission_stats.get("nMssn"),
                "missions_ok": mission_stats.get("nMssnOk"),
                "missions_failed": mission_stats.get("nMssnF"),
                "missions_cancelled": mission_stats.get("nMssnC"),
                "avg_mission_minutes": mission_stats.get("aMssnM"),
                "stuck_count": run_stats.get("nStuck"),
            },
            "battery": {
                "charge_cycles": bat_info.get("cCount"),
                "est_capacity_mah": charge_stats.get("estCap"),
                "manufacture_date": bat_info.get("mDate"),
            },
            "settings": {
                "passes": passes,
                "bin_pause": bool(reported.get("binPause")),
                "child_lock": bool(reported.get("childLock")),
            },
            "schedule": _parse_schedule(reported),
            "wifi": {
                "rssi": signal.get("rssi"),
                "snr": signal.get("snr"),
            },
            "position_supported": self._position_supported,
            "position": self._position,
        }

    def get_raw_state(self):
        """ Everything the robot reports, unparsed. For debugging: fields vary by model and firmware """
        if self._client is None:
            return {"alias": self.alias, "connected": False}

        async def _copy_reported():
            # Copy in the loop thread, so roombapy can't update the state while we're serializing it
            return copy.deepcopy(self._client.master_state.get("state", {}).get("reported", {}))
        reported = asyncio.run_coroutine_threadsafe(_copy_reported(), self._loop).result(timeout=5)
        return {"alias": self.alias, "connected": self._client.connected, "reported": reported}

    def _maybe_bcast_state(self):
        # The robot sends lots of messages, only announce when something we expose changed
        state = self.get_state()
        if state == self._last_bcast_state:
            return
        self._last_bcast_state = state
        self._on_state_change(self.alias, state)

    def send_command(self, cmd):
        """ Send a command (eg start, pause, dock, find) to the robot """
        if self._client is None or not self._client.connected:
            log.warning("Requested %s for %s, but it isn't connected", cmd, self.alias)
            return {"alias": self.alias, "status": "not_connected"}
        robot_cmd = cmd
        if cmd == "start" and self._client.current_state == ROOMBA_STATES["pause"]:
            # A start while paused would begin a new mission, instead of continuing the current one
            robot_cmd = "resume"
        log.info("Sending %s to %s", robot_cmd, self.alias)
        fut = asyncio.run_coroutine_threadsafe(self._client.send_command(robot_cmd), self._loop)
        fut.result(timeout=10)
        return {"alias": self.alias, "status": "ok"}

    def set_setting(self, setting, value):
        """ Change one of SETTINGS. The robot echoes the new value back, which triggers a state announcement """
        if setting not in SETTINGS:
            return {"alias": self.alias, "status": "unknown_setting"}
        if value not in SETTINGS[setting]:
            return {"alias": self.alias, "status": "bad_value"}
        if self._client is None or not self._client.connected:
            log.warning("Requested %s=%s for %s, but it isn't connected", setting, value, self.alias)
            return {"alias": self.alias, "status": "not_connected"}
        prefs = _setting_to_prefs(setting, value)
        log.info("Setting %s on %s", prefs, self.alias)
        fut = asyncio.run_coroutine_threadsafe(self._client.set_preferences(prefs), self._loop)
        fut.result(timeout=10)
        return {"alias": self.alias, "status": "ok"}

    def disconnect(self):
        """ Stop (re)connecting, and close the local connection to the robot """
        self._task.cancel()
        if self._client is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop).result(timeout=5)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            log.warning("Error disconnecting from %s: %s", self.alias, ex)
