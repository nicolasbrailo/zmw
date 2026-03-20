"""Unit tests for user_device_presence_mon.py"""
from unittest.mock import patch, Mock, call

from user_device_presence_mon import UserDevicePresenceMon


DEVICE_OWNERS = {
    "Nico": ["Pixel-9-Pro-XL", "N-s-S22"],
    "Belen": ["Belen-s-S25-Ultra"],
}


def make_mon(leave_cooldown_secs=0, **kw):
    cb = Mock()
    mon = UserDevicePresenceMon(
        DEVICE_OWNERS, leave_cooldown_secs=leave_cooldown_secs,
        on_state_change=cb, **kw)
    return mon, cb


class TestDeviceToUserMapping:
    """Test that device-to-user reverse mapping works correctly."""

    def test_hostname_lookup(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "aa:bb:cc:dd:ee:ff")
        cb.assert_called_once_with("Nico", "home", "Pixel-9-Pro-XL")

    def test_mac_lookup(self):
        cb = Mock()
        mon = UserDevicePresenceMon({"Nico": ["aa:bb:cc:dd:ee:ff"]},
                                    on_state_change=cb)
        mon.on_device_event("joined", "", "aa:bb:cc:dd:ee:ff")
        cb.assert_called_once_with("Nico", "home", "aa:bb:cc:dd:ee:ff")

    def test_unknown_device_no_callback(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Unknown-Phone", "ff:ff:ff:ff:ff:ff")
        cb.assert_not_called()

    def test_empty_owners(self):
        cb = Mock()
        mon = UserDevicePresenceMon({}, on_state_change=cb)
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "aa:bb:cc:dd:ee:ff")
        cb.assert_not_called()

    def test_unknown_event_type(self):
        mon, cb = make_mon()
        mon.on_device_event("rebooted", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()


class TestJoinEvents:
    """Test device join behavior and user-level deduplication."""

    def test_first_device_join_emits_home(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.assert_called_once_with("Nico", "home", "Pixel-9-Pro-XL")

    def test_second_device_join_same_user_is_deduplicated(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.reset_mock()
        mon.on_device_event("joined", "N-s-S22", "")
        cb.assert_not_called()

    def test_same_device_join_twice_is_deduplicated(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.reset_mock()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()

    def test_different_users_both_get_home_events(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("joined", "Belen-s-S25-Ultra", "")
        assert cb.call_count == 2


class TestLeaveEvents:
    """Test device leave behavior with no cooldown (immediate away)."""

    def test_last_device_leave_emits_away(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.reset_mock()
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_called_once_with("Nico", "away", "Pixel-9-Pro-XL")

    def test_leave_with_other_device_still_connected(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("joined", "N-s-S22", "")
        cb.reset_mock()
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()
        assert mon.user_states["Nico"] is True

    def test_leave_all_devices_emits_away(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("joined", "N-s-S22", "")
        cb.reset_mock()
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()
        mon.on_device_event("left", "N-s-S22", "")
        cb.assert_called_once_with("Nico", "away", "N-s-S22")

    def test_leave_already_away_is_deduplicated(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.reset_mock()
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()

    def test_leave_without_prior_join(self):
        mon, cb = make_mon()
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()


class TestLeaveCooldown:
    """Test the delayed away emission with cooldown."""

    @patch('user_device_presence_mon.threading.Timer')
    def test_leave_starts_timer(self, MockTimer):
        mock_timer = Mock()
        MockTimer.return_value = mock_timer
        mon, cb = make_mon(leave_cooldown_secs=60)
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.reset_mock()

        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        MockTimer.assert_called_once_with(60, mon._emit_away, args=("Nico", "Pixel-9-Pro-XL"))
        mock_timer.start.assert_called_once()
        # Away not emitted yet
        cb.assert_not_called()
        assert mon.user_states["Nico"] is True

    @patch('user_device_presence_mon.threading.Timer')
    def test_rejoin_during_cooldown_cancels_away(self, MockTimer):
        mock_timer = Mock()
        MockTimer.return_value = mock_timer
        mon, cb = make_mon(leave_cooldown_secs=60)
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.reset_mock()

        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()

        # Rejoin before timer fires
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mock_timer.cancel.assert_called_once()
        # No away was emitted, no home either (user was still "home")
        cb.assert_not_called()
        assert mon.user_states["Nico"] is True

    @patch('user_device_presence_mon.threading.Timer')
    def test_timer_fires_emits_away(self, MockTimer):
        mock_timer = Mock()
        MockTimer.return_value = mock_timer
        mon, cb = make_mon(leave_cooldown_secs=60)
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.reset_mock()

        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        # Simulate timer firing
        mon._emit_away("Nico", "Pixel-9-Pro-XL")
        cb.assert_called_once_with("Nico", "away", "Pixel-9-Pro-XL")
        assert mon.user_states["Nico"] is False

    @patch('user_device_presence_mon.threading.Timer')
    def test_no_duplicate_timer_on_second_leave(self, MockTimer):
        """If a second unknown device also leaves, don't start a second timer."""
        mock_timer = Mock()
        MockTimer.return_value = mock_timer
        mon, cb = make_mon(leave_cooldown_secs=60)
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        assert MockTimer.call_count == 1

        # Another leave for the same user (device never joined, so no-op)
        mon.on_device_event("left", "N-s-S22", "")
        assert MockTimer.call_count == 1

    @patch('user_device_presence_mon.threading.Timer')
    def test_full_cycle_with_cooldown(self, MockTimer):
        """home -> leave (pending) -> timer fires (away) -> rejoin (home)"""
        mock_timer = Mock()
        MockTimer.return_value = mock_timer
        mon, cb = make_mon(leave_cooldown_secs=60)

        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        assert cb.call_args == call("Nico", "home", "Pixel-9-Pro-XL")
        cb.reset_mock()

        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()

        # Timer fires
        mon._emit_away("Nico", "Pixel-9-Pro-XL")
        assert cb.call_args == call("Nico", "away", "Pixel-9-Pro-XL")
        cb.reset_mock()

        # Rejoin
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        assert cb.call_args == call("Nico", "home", "Pixel-9-Pro-XL")

    @patch('user_device_presence_mon.threading.Timer')
    def test_flaky_disconnect_reconnect_suppressed(self, MockTimer):
        """The core use case: brief disconnect+reconnect emits nothing."""
        mock_timer = Mock()
        MockTimer.return_value = mock_timer
        mon, cb = make_mon(leave_cooldown_secs=60)

        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.reset_mock()

        # Flaky disconnect
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        # Quick reconnect
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")

        # No state change callback was fired — user never appeared to leave
        cb.assert_not_called()
        assert mon.user_states["Nico"] is True

    @patch('user_device_presence_mon.threading.Timer')
    def test_cooldown_is_per_user(self, MockTimer):
        timers = [Mock(), Mock()]
        MockTimer.side_effect = timers
        mon, cb = make_mon(leave_cooldown_secs=60)

        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("joined", "Belen-s-S25-Ultra", "")
        cb.reset_mock()

        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        mon.on_device_event("left", "Belen-s-S25-Ultra", "")
        assert MockTimer.call_count == 2

        # Nico reconnects, Belen doesn't
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        timers[0].cancel.assert_called_once()
        timers[1].cancel.assert_not_called()

        # Belen's timer fires
        mon._emit_away("Belen", "Belen-s-S25-Ultra")
        cb.assert_called_once_with("Belen", "away", "Belen-s-S25-Ultra")


class TestUserStates:
    """Test the user_states property."""

    def test_empty_initially(self):
        mon, _ = make_mon()
        assert mon.user_states == {}

    def test_reflects_current_state(self):
        mon, _ = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("joined", "Belen-s-S25-Ultra", "")
        assert mon.user_states == {"Nico": True, "Belen": True}

        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        # With cooldown=0, away is immediate
        assert mon.user_states == {"Nico": False, "Belen": True}

    def test_returns_copy(self):
        mon, _ = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        states = mon.user_states
        states["Nico"] = False
        assert mon.user_states["Nico"] is True


class TestSeedConnectedDevice:
    """Test seeding presence state from already-connected devices at startup."""

    def test_seed_sets_user_home(self):
        mon, cb = make_mon()
        mon.seed_connected_device("Pixel-9-Pro-XL", "aa:bb")
        assert mon.user_states == {"Nico": True}
        cb.assert_not_called()

    def test_seed_unknown_device_ignored(self):
        mon, cb = make_mon()
        mon.seed_connected_device("Unknown-Phone", "ff:ff")
        assert mon.user_states == {}
        cb.assert_not_called()

    def test_seed_then_leave_emits_away(self):
        mon, cb = make_mon()
        mon.seed_connected_device("Pixel-9-Pro-XL", "aa:bb")
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_called_once_with("Nico", "away", "Pixel-9-Pro-XL")

    def test_seed_then_join_is_deduplicated(self):
        mon, cb = make_mon()
        mon.seed_connected_device("Pixel-9-Pro-XL", "aa:bb")
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()

    def test_seed_multiple_devices_same_user(self):
        mon, cb = make_mon()
        mon.seed_connected_device("Pixel-9-Pro-XL", "aa:bb")
        mon.seed_connected_device("N-s-S22", "cc:dd")
        assert mon.user_states == {"Nico": True}
        # Leave one — still home
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.assert_not_called()
        # Leave both — away
        mon.on_device_event("left", "N-s-S22", "")
        cb.assert_called_once_with("Nico", "away", "N-s-S22")


class TestRejoinAfterLeave:
    """Test the full home -> away -> home cycle."""

    def test_rejoin_after_away_emits_home(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.reset_mock()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        cb.assert_called_once_with("Nico", "home", "Pixel-9-Pro-XL")

    def test_rejoin_with_different_device(self):
        mon, cb = make_mon()
        mon.on_device_event("joined", "Pixel-9-Pro-XL", "")
        mon.on_device_event("left", "Pixel-9-Pro-XL", "")
        cb.reset_mock()
        mon.on_device_event("joined", "N-s-S22", "")
        cb.assert_called_once_with("Nico", "home", "N-s-S22")
