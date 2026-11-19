""" History of the last runs of each robot: missions (scheduled or not) and scheduled runs that didn't start.
Persisted in the runtime state cache, so it survives service restarts. """
import threading
import time
from collections import deque

from zzmw_lib.logs import build_logger
from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set

log = build_logger("ZmwSucksHistory")

_STATE_KEY = "zmw_sucks_run_history"

# Results of a run. "running" is only used until the mission ends.
RESULTS = {
    "running": "Mission in progress",
    "ok": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "unknown": "Ended, but the robot didn't count it as completed (or the service missed the end)",
    "missed": "Scheduled run that didn't start",
}


def _locked(method):
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class RunHistory:
    """ Keeps the last history_len runs of each robot. Entries are dicts (see get_mqtt_description in zmw_sucks),
    callers update them through this class so changes get persisted. Thread safe: the monitor's jobs update it while
    www/MQTT read it. """
    def __init__(self, history_len):
        self._lock = threading.RLock()
        self._history_len = history_len
        self._runs = {}
        cached = runtime_state_cache_get(_STATE_KEY) or {}
        for alias, runs in cached.items():
            self._runs_of(alias).extend(runs)
        if cached:
            log.info("Restored run history of %s", ', '.join(cached))

    def _runs_of(self, alias):
        return self._runs.setdefault(alias, deque(maxlen=self._history_len))

    def _save(self):
        runtime_state_cache_set(_STATE_KEY, {alias: list(runs) for alias, runs in self._runs.items()})

    @_locked
    def get(self):
        """ Map of robot alias to its runs, newest first """
        return {alias: [dict(run, problems=list(run["problems"])) for run in reversed(runs)]
                for alias, runs in self._runs.items()}

    def _new_run(self, alias, **fields):
        run = {
            "start": time.time(),
            "end": None,
            "result": "running",
            "scheduled": False,
            "scheduled_time": None,
            "initiator": None,
            "mission_id": None,
            "minutes": None,
            "sqft": None,
            "problems": [],
            "details": None,
        }
        run.update(fields)
        self._runs_of(alias).append(run)
        self._save()
        return run

    @_locked
    def mission_started(self, alias, mission_state, scheduled):
        """ A robot was seen running a mission. Returns its run. If the service restarted mid mission, this continues
        the run from before the restart; any other run still marked as running was missed ending. """
        mission_id = mission_state.get("id")
        for run in self._runs_of(alias):
            if run["result"] != "running":
                continue
            if mission_id is not None and run["mission_id"] == mission_id:
                log.info("%s continues mission %s from before the service restarted", alias, mission_id)
                return run
            run["result"] = "unknown"
            run["details"] = "Service didn't see this mission end (eg it was restarting)"
        start = mission_state.get("start_time") or time.time()
        return self._new_run(alias, start=start, scheduled=scheduled, initiator=mission_state.get("initiator"),
                             mission_id=mission_id)

    @_locked
    def mission_progress(self, run, mission_state):
        """ Latest duration and area of a running mission (the robot resets them when the mission ends) """
        for key in ("minutes", "sqft"):
            if mission_state.get(key) is not None:
                run[key] = mission_state[key]
        self._save()

    @_locked
    def mark_scheduled(self, run, scheduled_time):
        run["scheduled"] = True
        run["scheduled_time"] = scheduled_time
        self._save()

    @_locked
    def add_problem(self, run, problem):
        if problem not in run["problems"]:
            run["problems"].append(problem)
            self._save()

    @_locked
    def mission_ended(self, run, result, details):
        run["end"] = time.time()
        run["result"] = result
        run["details"] = details
        self._save()

    @_locked
    def scheduled_run_missed(self, alias, scheduled_time, details):
        self._new_run(alias, end=time.time(), result="missed", scheduled=True, scheduled_time=scheduled_time,
                      details=details)
