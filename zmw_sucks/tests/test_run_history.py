"""Unit tests for run_history.py, and how MissionMonitor fills it"""
from unittest.mock import Mock, patch

import pytest

from mission_monitor import MissionMonitor
from run_history import RunHistory


@pytest.fixture
def cache():
    """ In-memory runtime state cache """
    store = {}
    with patch('run_history.runtime_state_cache_get', side_effect=store.get), \
         patch('run_history.runtime_state_cache_set', side_effect=store.__setitem__):
        yield store


def _mission(mission_id="m1", minutes=0, sqft=0, initiator="localApp"):
    return {"id": mission_id, "cycle": "clean", "initiator": initiator, "start_time": 1000,
            "minutes": minutes, "sqft": sqft}


class TestRunHistory:
    def test_empty(self, cache):
        assert RunHistory(5).get() == {}

    def test_newest_first_and_capped(self, cache):
        hist = RunHistory(2)
        for i in range(3):
            hist.mission_ended(hist.mission_started("R", _mission(f"m{i}"), False), "ok", None)
        runs = hist.get()["R"]
        assert [r["mission_id"] for r in runs] == ["m2", "m1"]

    def test_mission_lifecycle(self, cache):
        hist = RunHistory(5)
        run = hist.mission_started("R", _mission(), False)
        hist.mission_progress(run, _mission(minutes=12, sqft=100))
        hist.add_problem(run, "is stuck")
        hist.add_problem(run, "is stuck")
        hist.mission_ended(run, "failed", "Stuck, battery 20%")
        got = hist.get()["R"][0]
        assert got["start"] == 1000
        assert got["end"] is not None
        assert got["result"] == "failed"
        assert got["minutes"] == 12
        assert got["sqft"] == 100
        assert got["problems"] == ["is stuck"]
        assert got["details"] == "Stuck, battery 20%"

    def test_missed_run(self, cache):
        hist = RunHistory(5)
        hist.scheduled_run_missed("R", "10:00", "not cleaning")
        got = hist.get()["R"][0]
        assert got["result"] == "missed"
        assert got["scheduled"] and got["scheduled_time"] == "10:00"

    def test_survives_restart(self, cache):
        hist = RunHistory(5)
        hist.mission_started("R", _mission(), True)
        restarted = RunHistory(5)
        assert restarted.get()["R"][0]["result"] == "running"

    def test_restart_mid_mission_continues_run(self, cache):
        RunHistory(5).mission_started("R", _mission("m1"), True)
        hist = RunHistory(5)
        hist.mission_started("R", _mission("m1"), False)
        runs = hist.get()["R"]
        assert len(runs) == 1
        assert runs[0]["scheduled"]

    def test_run_that_ended_while_service_was_down(self, cache):
        RunHistory(5).mission_started("R", _mission("m1"), False)
        hist = RunHistory(5)
        hist.mission_started("R", _mission("m2"), False)
        runs = hist.get()["R"]
        assert [(r["mission_id"], r["result"]) for r in runs] == [("m2", "running"), ("m1", "unknown")]


class FakeRobot:
    def __init__(self):
        self.alias = "R"
        self.service_schedule = None
        self.mission = None
        self.ok = 0

    def get_state(self):
        return {
            "alias": self.alias, "connected": True, "state": "Running" if self.mission else "Charging",
            "phase": "run" if self.mission else "charge", "schedule": None,
            "mission": self.mission or {"id": None, "cycle": "none", "initiator": None},
            "error": None, "error_code": None, "bin_full": False, "battery_pct": 80,
            "lifetime": {"missions_ok": self.ok, "missions_failed": 0, "missions_cancelled": 0},
        }


class TestMonitorFillsHistory:
    def test_completed_mission(self, cache):
        robot = FakeRobot()
        hist = RunHistory(5)
        mon = MissionMonitor(Mock(), lambda: [robot], Mock(), hist,
                             notify_on_schedule_success=False, notify_on_schedule_failure=True)
        robot.mission = _mission(minutes=5, sqft=50)
        mon._check_missions()
        assert hist.get()["R"][0]["result"] == "running"
        robot.mission = _mission(minutes=30, sqft=300)
        mon._check_missions()
        robot.mission = None
        robot.ok = 1
        mon._check_missions()
        got = hist.get()["R"][0]
        assert got["result"] == "ok"
        assert got["minutes"] == 30
        assert got["sqft"] == 300
