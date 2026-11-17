"""Unit tests for mission_monitor.py: following the robot's own schedule or the one in the service config"""
from datetime import datetime
from unittest.mock import Mock

import pytest

import mission_monitor
from mission_monitor import MissionMonitor
from roomba import parse_service_schedule

# 2026-11-16 is a Monday
MON = (2026, 11, 16)
TUE = (2026, 11, 17)


class _FakeDatetime(datetime):
    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.replace(tzinfo=tz)


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(mission_monitor, "datetime", _FakeDatetime)

    def set_time(day, hour, minute, second=0):
        _FakeDatetime.current = datetime(*day, hour, minute, second)
    return set_time


def _robot_schedule(*entries, paused=False):
    return {"paused": paused, "timezone": None, "entries": [
        {"enabled": True, "days": [day], "day_nums": [day_num], "hour": hour, "min": minute, "command": "start"}
        for day, day_num, hour, minute in entries]}


class FakeRobot:
    def __init__(self, service_schedule=None, robot_schedule=None, cleaning=False, connected=True):
        self.alias = "Robot"
        self.service_schedule = None
        if service_schedule is not None:
            self.service_schedule = parse_service_schedule({"alias": self.alias, "schedule": service_schedule})
        self.robot_schedule = robot_schedule or _robot_schedule()
        self.cleaning = cleaning
        self.connected = connected
        self.send_command = Mock(return_value={"alias": self.alias, "status": "ok"})

    def get_state(self):
        if not self.connected:
            return {"alias": self.alias, "connected": False}
        return {
            "alias": self.alias,
            "connected": True,
            "state": "Running" if self.cleaning else "Charging",
            "schedule": self.robot_schedule,
            "mission": {"cycle": "clean" if self.cleaning else "none", "initiator": "localApp"},
            "error": None,
            "bin_full": False,
            "battery_pct": 100,
        }


def _monitor(robot):
    notify = Mock()
    mon = MissionMonitor(Mock(), lambda: [robot], notify,
                         notify_on_schedule_success=False, notify_on_schedule_failure=True)
    return mon, notify


SERVICE_SCHED = [{"day": "Mon", "time": "10:00"}]


class TestServiceSchedule:
    def test_starts_run_when_due(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED)
        mon, _ = _monitor(robot)
        clock(MON, 9, 59, 30)
        mon._check_schedules()
        robot.send_command.assert_not_called()
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        robot.send_command.assert_called_once_with("start")
        # Only once per run
        clock(MON, 10, 1, 30)
        mon._check_schedules()
        robot.send_command.assert_called_once_with("start")

    def test_late_start_within_window(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED)
        mon, _ = _monitor(robot)
        clock(MON, 10, 1, 59)
        mon._check_schedules()
        robot.send_command.assert_called_once_with("start")

    def test_no_start_too_late(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED)
        mon, _ = _monitor(robot)
        clock(MON, 10, 2, 30)
        mon._check_schedules()
        robot.send_command.assert_not_called()

    def test_no_start_other_day(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED)
        mon, _ = _monitor(robot)
        clock(TUE, 10, 0, 30)
        mon._check_schedules()
        robot.send_command.assert_not_called()

    def test_no_start_if_already_cleaning(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED, cleaning=True)
        mon, _ = _monitor(robot)
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        robot.send_command.assert_not_called()

    def test_run_that_started_is_ok(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED)
        mon, notify = _monitor(robot)
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        robot.cleaning = True
        clock(MON, 10, 2, 30)
        mon._check_schedules()
        assert mon.get_alerts() == []
        notify.assert_not_called()

    def test_run_that_didnt_start_alerts(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED)
        mon, notify = _monitor(robot)
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        clock(MON, 10, 2, 30)
        mon._check_schedules()
        assert len(mon.get_alerts()) == 1
        assert "isn't cleaning" in mon.get_alerts()[0]
        notify.assert_called_once()

    def test_never_connected_robot_still_gets_started(self, clock):
        # Unknown own schedule: assume it has none. The start fails, and the check of the run reports it.
        robot = FakeRobot(service_schedule=SERVICE_SCHED, connected=False)
        mon, _ = _monitor(robot)
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        robot.send_command.assert_called_once_with("start")


class TestScheduleConflict:
    def test_robot_schedule_wins(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED, robot_schedule=_robot_schedule(("Tue", 2, 9, 0)))
        mon, _ = _monitor(robot)
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        robot.send_command.assert_not_called()
        assert len(mon.get_alerts()) == 1
        assert "has its own schedule" in mon.get_alerts()[0]

    def test_robot_schedule_on_hold_still_wins(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED,
                          robot_schedule=_robot_schedule(("Tue", 2, 9, 0), paused=True))
        mon, _ = _monitor(robot)
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        robot.send_command.assert_not_called()
        assert "has its own schedule" in mon.get_alerts()[0]

    def test_conflict_clears_when_robot_schedule_removed(self, clock):
        robot = FakeRobot(service_schedule=SERVICE_SCHED, robot_schedule=_robot_schedule(("Tue", 2, 9, 0)))
        mon, _ = _monitor(robot)
        clock(MON, 9, 59, 0)
        mon._check_schedules()
        assert mon.get_alerts()
        robot.robot_schedule = _robot_schedule()
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        assert mon.get_alerts() == []
        robot.send_command.assert_called_once_with("start")

    def test_robot_schedule_only_is_monitored_not_started(self, clock):
        # Existing behaviour (eg robots scheduled in the iRobot app): the service only checks the run started
        robot = FakeRobot(robot_schedule=_robot_schedule(("Mon", 1, 10, 0)))
        mon, _ = _monitor(robot)
        clock(MON, 10, 0, 30)
        mon._check_schedules()
        robot.send_command.assert_not_called()
        assert mon.get_alerts() == []
        clock(MON, 10, 2, 30)
        mon._check_schedules()
        assert "isn't cleaning" in mon.get_alerts()[0]

    def test_no_schedule_does_nothing(self, clock):
        robot = FakeRobot()
        mon, notify = _monitor(robot)
        for minute in range(0, 10):
            clock(MON, 10, minute, 30)
            mon._check_schedules()
        robot.send_command.assert_not_called()
        assert mon.get_alerts() == []
        notify.assert_not_called()
