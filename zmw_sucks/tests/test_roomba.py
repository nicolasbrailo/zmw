"""Unit tests for roomba.py: config parsing, discovery, and reconnect decisions"""
import asyncio
from types import SimpleNamespace

import pytest

import roomba
from roomba import (Discovery, Roomba, get_discovery_mechanism, has_own_schedule, parse_service_schedule,
                    _parse_schedule)


def _cfg(**kw):
    return {"alias": "Robot", "blid": "BLID1", "password": "x", **kw}


class TestServiceSchedule:
    def test_no_schedule(self):
        assert parse_service_schedule(_cfg()) is None
        assert parse_service_schedule(_cfg(schedule=[])) is None

    def test_parses_entries(self):
        sched = parse_service_schedule(_cfg(schedule=[{"day": "Mon", "time": "10:00"},
                                                      {"day": "Sun", "time": "7:05"}]))
        assert sched["paused"] is False
        assert sched["timezone"] is None
        assert sched["entries"] == [
            {"enabled": True, "days": ["Mon"], "day_nums": [1], "hour": 10, "min": 0, "command": "start"},
            {"enabled": True, "days": ["Sun"], "day_nums": [0], "hour": 7, "min": 5, "command": "start"},
        ]

    @pytest.mark.parametrize("entry", [
        {"day": "Monday", "time": "10:00"},
        {"day": "mon", "time": "10:00"},
        {"time": "10:00"},
        {"day": "Mon"},
        {"day": "Mon", "time": "24:00"},
        {"day": "Mon", "time": "10:60"},
        {"day": "Mon", "time": "10"},
        {"day": "Mon", "time": "10:00:00"},
        {"day": "Mon", "time": "ab:cd"},
    ])
    def test_rejects_bad_entries(self, entry):
        with pytest.raises(ValueError):
            parse_service_schedule(_cfg(schedule=[entry]))


class TestRobotSchedule:
    def test_parse_robot_schedule(self):
        reported = {
            "schedHold": True,
            "timezone": "Europe/London",
            "cleanSchedule2": [
                {"enabled": True, "start": {"day": [1, 3], "hour": 10, "min": 30}, "cmd": {"command": "start"}},
                {"enabled": False, "start": {"day": [6], "hour": 9, "min": 0}, "cmd": {"command": "start"}},
            ],
        }
        sched = _parse_schedule(reported)
        assert sched["paused"] is True
        assert sched["timezone"] == "Europe/London"
        assert sched["entries"][0]["days"] == ["Mon", "Wed"]
        assert (sched["entries"][0]["hour"], sched["entries"][0]["min"]) == (10, 30)
        assert sched["entries"][1]["enabled"] is False

    def test_parse_legacy_robot_schedule(self):
        reported = {
            "timezone": "Europe/London",
            "cleanSchedule": {"cycle": ["none", "start", "start", "none", "start", "start", "none"],
                              "h": [9, 9, 9, 9, 9, 9, 8], "m": [0, 0, 0, 0, 0, 30, 0]},
        }
        sched = _parse_schedule(reported)
        assert sched["paused"] is False
        # Days without a run aren't entries
        assert [e["days"] for e in sched["entries"]] == [["Mon"], ["Tue"], ["Thu"], ["Fri"]]
        assert all(e["enabled"] for e in sched["entries"])
        assert (sched["entries"][3]["hour"], sched["entries"][3]["min"]) == (9, 30)
        assert sched["entries"][3]["day_nums"] == [5]
        assert has_own_schedule(sched)
        assert _parse_schedule({"cleanSchedule": {"cycle": ["none"] * 7, "h": [9] * 7, "m": [0] * 7}})["entries"] == []

    def test_no_robot_schedule(self):
        assert _parse_schedule({})["entries"] == []

    def test_has_own_schedule(self):
        enabled = {"enabled": True}
        disabled = {"enabled": False}
        assert not has_own_schedule(None)
        assert not has_own_schedule({"paused": False, "entries": []})
        assert not has_own_schedule({"paused": False, "entries": [disabled]})
        assert has_own_schedule({"paused": False, "entries": [disabled, enabled]})
        # On hold still counts: the robot may resume it
        assert has_own_schedule({"paused": True, "entries": [enabled]})


class TestDiscoveryMechanism:
    def test_defaults(self):
        assert get_discovery_mechanism(_cfg()) == "broadcast"
        assert get_discovery_mechanism(_cfg(ip="10.0.0.1")) == "fixed_ip"

    def test_explicit(self):
        assert get_discovery_mechanism(_cfg(discovery_mechanism="unifi")) == "unifi"
        assert get_discovery_mechanism(_cfg(discovery_mechanism="fixed_ip", ip="10.0.0.1")) == "fixed_ip"

    @pytest.mark.parametrize("cfg", [
        _cfg(discovery_mechanism="magic"),
        _cfg(discovery_mechanism="fixed_ip"),
        _cfg(discovery_mechanism="unifi", ip="10.0.0.1"),
        _cfg(discovery_mechanism="broadcast", ip="10.0.0.1"),
    ])
    def test_rejects_bad_config(self, cfg):
        with pytest.raises(ValueError):
            get_discovery_mechanism(cfg)


def _robot_info(blid, ip):
    return SimpleNamespace(blid=blid, ip=ip, robot_name=f"Robot {blid}")


class _FakeRoombaDiscovery:
    """ Stands in for roombapy's RoombaDiscovery: robots answer from the class level list """
    robots = []
    fail = False

    async def get_all(self, timeout):
        if self.fail:
            raise OSError("boom")
        return list(self.robots)

    async def get(self, ip, timeout):
        if self.fail:
            raise OSError("boom")
        return next((r for r in self.robots if r.ip == ip), None)

    async def aclose(self):
        pass


@pytest.fixture
def fake_discovery(monkeypatch):
    monkeypatch.setattr(roomba, "RoombaDiscovery", _FakeRoombaDiscovery)
    monkeypatch.setattr(_FakeRoombaDiscovery, "robots", [_robot_info("A", "10.0.0.1"), _robot_info("B", "10.10.30.2")])
    monkeypatch.setattr(_FakeRoombaDiscovery, "fail", False)
    return _FakeRoombaDiscovery


class TestDiscovery:
    def test_broadcast(self, fake_discovery):
        assert asyncio.run(Discovery().find_ip("B")) == "10.10.30.2"

    def test_broadcast_not_found(self, fake_discovery):
        assert asyncio.run(Discovery().find_ip("C")) is None

    def test_probe(self, fake_discovery):
        assert asyncio.run(Discovery().find_ip("B", "10.10.30.2")) == "10.10.30.2"

    def test_probe_finds_other_robot(self, fake_discovery):
        assert asyncio.run(Discovery().find_ip("A", "10.10.30.2")) is None

    def test_probe_nobody_there(self, fake_discovery):
        assert asyncio.run(Discovery().find_ip("A", "10.0.0.99")) is None

    def test_discovery_error(self, fake_discovery):
        fake_discovery.fail = True
        assert asyncio.run(Discovery().find_ip("A")) is None
        assert asyncio.run(Discovery().find_ip("A", "10.0.0.1")) is None


def _connected_roomba(fixed_ip=None, auth_error=None, connected=True):
    """ A Roomba with a client, without starting its connection task """
    r = Roomba.__new__(Roomba)
    r.alias = "Robot"
    r._ip = "10.0.0.1"
    r._fixed_ip = fixed_ip
    r.auth_rejected = False
    r._client = SimpleNamespace(auth_error=auth_error, connected=connected)
    return r


class TestWaitUntilLost:
    @pytest.fixture(autouse=True)
    def fast_checks(self, monkeypatch):
        monkeypatch.setattr(roomba, "_CONNECTION_CHECK_SECS", 0)
        monkeypatch.setattr(roomba, "_REDISCOVER_AFTER_DISCONNECTED_SECS", -1)

    def test_auth_error_on_reconnect_rediscovers(self):
        # The robot's old IP may now belong to another robot, which rejects our credentials
        r = _connected_roomba(auth_error=Exception("rejected"), connected=False)
        assert asyncio.run(r._wait_until_lost()) is True
        assert r.auth_rejected is False

    def test_auth_error_with_fixed_ip_is_final(self):
        r = _connected_roomba(fixed_ip="10.0.0.1", auth_error=Exception("rejected"), connected=False)
        assert asyncio.run(r._wait_until_lost()) is False
        assert r.auth_rejected is True

    def test_disconnected_rediscovers(self):
        r = _connected_roomba(connected=False)
        assert asyncio.run(r._wait_until_lost()) is True
        assert r.auth_rejected is False
