""" Checks that robots run when scheduled, and that their missions don't run into trouble. Problems (and, optionally,
successful scheduled runs) are reported with a notify callback (eg Telegram). Missed runs are kept as alerts until
they clear. Also starts the runs of robots with a schedule in the service config, instead of their own. """
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zzmw_lib.logs import build_logger

from roomba import has_own_schedule

log = build_logger("ZmwSucksMonitor")

# A scheduled run is checked this long after it should have started, so the robot had time to report its new state.
# Runs in the service schedule are started up to this long after they're due (eg the service was restarting).
_SCHEDULE_CHECK_DELAY = timedelta(minutes=2)
# Scheduled runs older than this are not checked (eg the service started well after a run was due)
_SCHEDULE_CHECK_WINDOW = timedelta(minutes=10)
# How often to check robots that are running a mission
MISSION_CHECK_SECS = 5 * 60
# How often to look for scheduled runs that are due for a check
SCHEDULE_CHECK_SECS = 60
# The robot may update its mission counters a bit after the mission ends. If none changed when a mission ended,
# wait this many more mission checks before deciding how it went.
_MAX_CHECKS_WAITING_FOR_RESULT = 2


def _is_mission_active(state):
    return state.get("mission", {}).get("cycle") not in (None, "none")


def _describe(state):
    """ Short state description, with anything that may explain a problem """
    parts = [state.get("state") or "unknown state"]
    if state.get("error"):
        parts.append(f"error: {state['error']}")
    if state.get("bin_full"):
        parts.append("bin full")
    if state.get("battery_pct") is not None:
        parts.append(f"battery {state['battery_pct']}%")
    return ', '.join(parts)


def _mission_problems(state):
    """ Problems of a robot running a mission, as {key: description} """
    problems = {}
    if state.get("phase") == "stuck":
        problems["stuck"] = "is stuck"
    if state.get("error"):
        problems[f"error_{state['error_code']}"] = f"reports an error: {state['error']}"
    if state.get("bin_full"):
        problems["bin_full"] = "has a full bin"
    return problems


def _mission_counters(state):
    lifetime = state["lifetime"]
    return {"ok": lifetime["missions_ok"], "failed": lifetime["missions_failed"],
            "cancelled": lifetime["missions_cancelled"]}


def _counter_increased(before, now, name):
    return before[name] is not None and now[name] is not None and now[name] > before[name]


class MissionMonitor:
    """ Uses the service scheduler; get_robots returns the list of Roomba objects to monitor. Problems in missions
    not started by the schedule are always notified; for scheduled runs, it depends on notify_on_schedule_* """
    def __init__(self, sched, get_robots, notify, notify_on_schedule_success, notify_on_schedule_failure):
        self._get_robots = get_robots
        self._notify = notify
        self._notify_on_schedule_success = notify_on_schedule_success
        self._notify_on_schedule_failure = notify_on_schedule_failure
        # Last known schedule of each robot: a robot that went offline should still be checked
        self._known_schedules = {}
        # Scheduled runs already checked, as alias -> set of datetimes
        self._checked_runs = {}
        # Runs of the service schedule already started, as alias -> set of datetimes
        self._started_runs = {}
        # Robots with a service schedule that is ignored, because the robot has its own
        self._ignoring_service_schedule = set()
        # Scheduled runs that didn't start, as alias -> message. Cleared when the robot starts a mission
        self._missed_runs = {}
        # Robots seen starting a scheduled run, in case the robot doesn't report the schedule as the initiator
        self._started_scheduled_run = set()
        # Robots running a mission, as alias -> {counters at mission start, problems already reported, ...}
        self._active_missions = {}
        sched.add_job(self._check_schedules, 'interval', seconds=SCHEDULE_CHECK_SECS)
        sched.add_job(self._check_missions, 'interval', seconds=MISSION_CHECK_SECS)

    def get_alerts(self):
        """ Problems that haven't cleared yet """
        conflicts = [f"{alias} has its own schedule, ignoring the one in the service config"
                     for alias in sorted(self._ignoring_service_schedule)]
        return list(self._missed_runs.values()) + conflicts

    def _notify_mission_problem(self, mission, msg):
        log.warning(msg)
        if not mission["scheduled"] or self._notify_on_schedule_failure:
            self._notify(msg)

    def _check_schedules(self):
        for robot in self._get_robots():
            try:
                self._check_robot_schedule(robot)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Failed to check schedule of %s", robot.alias)

    def _pick_schedule(self, robot):
        """ The schedule to follow: the one in the service config, unless the robot has its own (running both would
        clean twice). If the robot was never seen connected, assume it has none """
        robot_schedule = self._known_schedules.get(robot.alias)
        if robot.service_schedule is None:
            return robot_schedule
        if has_own_schedule(robot_schedule):
            if robot.alias not in self._ignoring_service_schedule:
                log.error("%s has its own schedule (eg set in the iRobot app), ignoring the schedule in the service "
                          "config. Remove one of them.", robot.alias)
                self._ignoring_service_schedule.add(robot.alias)
            return robot_schedule
        if robot.alias in self._ignoring_service_schedule:
            log.info("%s no longer has its own schedule, will follow the one in the service config", robot.alias)
            self._ignoring_service_schedule.discard(robot.alias)
        return robot.service_schedule

    def _check_robot_schedule(self, robot):
        state = robot.get_state()
        if state["connected"]:
            self._known_schedules[robot.alias] = state["schedule"]
        schedule = self._pick_schedule(robot)
        if schedule is None or schedule["paused"]:
            return
        run_by_service = schedule is robot.service_schedule

        try:
            tz = ZoneInfo(schedule["timezone"]) if schedule["timezone"] else None
        except ZoneInfoNotFoundError:
            log.warning("%s reports unknown timezone %s, using local time", robot.alias, schedule["timezone"])
            tz = None
        now = datetime.now(tz)
        # Robot days start on Sunday, Python's on Monday
        robot_today = (now.weekday() + 1) % 7

        checked = self._checked_runs.setdefault(robot.alias, set())
        started = self._started_runs.setdefault(robot.alias, set())
        # Forget runs that can't be checked (or started) again anyway
        checked -= {run for run in checked if now - run > timedelta(days=1)}
        started -= {run for run in started if now - run > timedelta(days=1)}

        for entry in schedule["entries"]:
            if not entry["enabled"] or robot_today not in entry["day_nums"] or entry["hour"] is None:
                continue
            run = now.replace(hour=entry["hour"], minute=entry["min"] or 0, second=0, microsecond=0)
            if run_by_service and run not in started and run <= now < run + _SCHEDULE_CHECK_DELAY:
                started.add(run)
                self._start_scheduled_run(robot, state, run)
                # state is from before the start: check on a later round, once the robot reported its new state
                continue
            if run in checked or not run + _SCHEDULE_CHECK_DELAY <= now < run + _SCHEDULE_CHECK_WINDOW:
                continue
            checked.add(run)
            self._check_scheduled_run(robot, state, run)

    def _start_scheduled_run(self, robot, state, run):
        run_time = run.strftime("%H:%M")
        if _is_mission_active(state):
            log.info("%s is already cleaning, won't start its %s scheduled run", robot.alias, run_time)
            return
        log.info("Starting %s scheduled run of %s", run_time, robot.alias)
        # If the robot isn't connected, this logs it. The check of this run will report it.
        robot.send_command("start")

    def _check_scheduled_run(self, robot, state, run):
        run_time = run.strftime("%H:%M")
        if not state["connected"]:
            msg = f"{robot.alias} was scheduled to start at {run_time}, but it's not connected: can't tell if it did"
        elif not _is_mission_active(state):
            msg = f"{robot.alias} was scheduled to start at {run_time}, but it isn't cleaning ({_describe(state)})"
        else:
            log.info("%s started its %s scheduled run", robot.alias, run_time)
            mission = self._active_missions.get(robot.alias)
            if mission is not None:
                mission["scheduled"] = True
            else:
                self._started_scheduled_run.add(robot.alias)
            return
        log.warning(msg)
        self._missed_runs[robot.alias] = msg
        if self._notify_on_schedule_failure:
            self._notify(msg)

    def _check_missions(self):
        for robot in self._get_robots():
            try:
                self._check_robot_mission(robot)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Failed to check mission of %s", robot.alias)

    def _check_robot_mission(self, robot):
        state = robot.get_state()
        mission = self._active_missions.get(robot.alias)

        if not state["connected"]:
            if mission is not None and not mission["reported_disconnect"]:
                mission["reported_disconnect"] = True
                self._notify_mission_problem(mission, f"{robot.alias} disconnected during a mission")
            return

        if not _is_mission_active(state):
            if mission is not None and self._on_mission_ended(robot, state, mission):
                del self._active_missions[robot.alias]
            return

        if mission is None:
            scheduled = (state["mission"]["initiator"] == "schedule"
                         or robot.alias in self._started_scheduled_run)
            self._started_scheduled_run.discard(robot.alias)
            log.info("%s is running a %smission", robot.alias, "scheduled " if scheduled else "")
            self._missed_runs.pop(robot.alias, None)
            mission = {"counters": _mission_counters(state), "scheduled": scheduled,
                       "problems": set(), "reported_disconnect": False, "checks_waiting_for_result": 0}
            self._active_missions[robot.alias] = mission
        mission["reported_disconnect"] = False
        mission["checks_waiting_for_result"] = 0

        problems = _mission_problems(state)
        for key, descr in problems.items():
            if key not in mission["problems"]:
                self._notify_mission_problem(mission, f"{robot.alias} {descr} ({_describe(state)})")
        # Forget problems that cleared, so they're reported again if they come back
        mission["problems"] = set(problems)

    def _on_mission_ended(self, robot, state, mission):
        """ Report how the mission went. Returns False if it's too early to tell, and should be checked again """
        before = mission["counters"]
        now = _mission_counters(state)
        if _counter_increased(before, now, "ok"):
            result = "ok"
        elif _counter_increased(before, now, "failed"):
            result = "failed"
        elif _counter_increased(before, now, "cancelled"):
            result = "cancelled"
        elif mission["checks_waiting_for_result"] < _MAX_CHECKS_WAITING_FOR_RESULT:
            mission["checks_waiting_for_result"] += 1
            return False
        else:
            result = "unknown"

        what = "scheduled run" if mission["scheduled"] else "mission"
        msgs = {
            "ok": f"{robot.alias} finished its {what} successfully",
            "failed": f"{robot.alias} {what} failed ({_describe(state)})",
            "cancelled": f"{robot.alias} {what} was cancelled ({_describe(state)})",
            "unknown": f"{robot.alias} {what} ended, but the robot didn't count it as completed ({_describe(state)})",
        }
        msg = msgs[result]
        log.info(msg)

        if mission["scheduled"]:
            if result == "ok" and self._notify_on_schedule_success:
                self._notify(msg)
            elif result != "ok" and self._notify_on_schedule_failure:
                self._notify(msg)
        elif result == "failed":
            # Missions not started by the schedule were probably started by someone at home: only a failure
            # is worth a message
            self._notify(msg)
        return True
