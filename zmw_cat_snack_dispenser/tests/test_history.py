import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from history import DispensingHistory


@pytest.fixture(autouse=True)
def mock_runtime_state_cache():
    """Mock the runtime state cache to prevent state restoration during tests."""
    with patch('history.runtime_state_cache_get', return_value=None), \
         patch('history.runtime_state_cache_set'):
        yield


class TestGetHistory:
    """Tests for get_history method."""

    def test_get_history_returns_empty_list_initially(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())
        assert history.get_history() == []

    def test_get_history_returns_entries_in_order(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer.return_value = Mock()
            history.register_request("source1", serving_size=1)
            history.register_request("source2", serving_size=2)
            history.register_request("source3", serving_size=3)

        entries = history.get_history()
        assert len(entries) == 3
        assert entries[0]['source'] == "source1"
        assert entries[1]['source'] == "source2"
        assert entries[2]['source'] == "source3"


class TestRegisterRequest:
    """Tests for register_request method."""

    def test_register_request_creates_history_entry(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer.return_value = Mock()
            result = history.register_request("manual", serving_size=2)

        assert result is True
        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['source'] == "manual"
        assert entries[0]['serving_size_requested'] == 2
        assert entries[0]['dispense_event_id'] == 1
        assert entries[0]['unit_acknowledged'] is False

    def test_register_request_starts_timeout_timer(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer_instance = Mock()
            mock_timer.return_value = mock_timer_instance

            history.register_request("manual", serving_size=1)

            mock_timer.assert_called_once()
            mock_timer_instance.start.assert_called_once()

    def test_register_request_when_pending_returns_false_and_registers_error(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer.return_value = Mock()

            # First request succeeds
            result1 = history.register_request("first", serving_size=1)
            assert result1 is True

            # Second request while first is pending should fail
            result2 = history.register_request("second", serving_size=1)
            assert result2 is False

        # Should have 2 entries: the first request and the error
        entries = history.get_history()
        assert len(entries) == 2
        assert entries[0]['source'] == "first"
        assert entries[1]['source'] == "second"
        assert entries[1]['error'] is not None
        assert "Unacknowledged dispensing in progress" in entries[1]['error']

    def test_register_request_error_message_includes_details(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer.return_value = Mock()

            history.register_request("first", serving_size=1)
            history.register_request("second", serving_size=1)

        entries = history.get_history()
        error_entry = entries[1]
        assert "event 1" in error_entry['error']
        assert "test_feeder" in error_entry['error']


class TestRegisterZigbeeDispense:
    """Tests for register_zigbee_dispense method."""

    def test_acknowledge_entry_within_timeout(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer_instance = Mock()
            mock_timer.return_value = mock_timer_instance

            history.register_request("manual", serving_size=1)

        # Acknowledge immediately (within timeout)
        history.register_zigbee_dispense(portions_dispensed=1, weight_dispensed=50)

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['unit_acknowledged'] is True
        assert entries[0]['portions_dispensed'] == 1
        assert entries[0]['weight_dispensed'] == 50
        assert entries[0]['time_acknowledged'] is not None

    def test_acknowledge_cancels_pending_timer(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer_instance = Mock()
            mock_timer.return_value = mock_timer_instance

            history.register_request("manual", serving_size=1)
            history.register_zigbee_dispense(portions_dispensed=1, weight_dispensed=50)

            mock_timer_instance.cancel.assert_called_once()

    def test_unauthorized_event_when_no_unacked_entry(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        # No prior request, just a zigbee dispense
        history.register_zigbee_dispense(portions_dispensed=2, weight_dispensed=100)

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['source'] == 'Unauthorized Zigbee request'
        assert entries[0]['error'] is not None
        assert "different service" in entries[0]['error']
        assert entries[0]['portions_dispensed'] == 2
        assert entries[0]['unit_acknowledged'] is True

    def test_dont_acknowledge_entry_older_than_5x_timeout(self):
        """Entry older than 5x timeout should not be acknowledged."""
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())
        # Default timeout is 5 seconds, so 5x = 25 seconds

        with patch('history.threading.Timer') as mock_timer:
            mock_timer.return_value = Mock()
            history.register_request("manual", serving_size=1)

        # Make the entry appear old by patching datetime.now in the dispense call
        entries = history.get_history()
        # Manually set the time_requested to be old
        entries[0]['time_requested'] = datetime.now() - timedelta(seconds=400)

        # Clear the pending job (simulating timeout already fired)
        history._pending_dispense_timeout_job = None

        history.register_zigbee_dispense(portions_dispensed=1, weight_dispensed=50)

        # Should have 2 entries: original (still unacked) and unauthorized
        all_entries = history.get_history()
        assert len(all_entries) == 2
        assert all_entries[0]['unit_acknowledged'] is False  # Original not acknowledged
        assert all_entries[1]['source'] == 'Unauthorized Zigbee request'

    def test_acknowledge_late_entry_within_5x_timeout(self):
        """Entry within 5x timeout should still be acknowledged with warning."""
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        with patch('history.threading.Timer') as mock_timer:
            mock_timer.return_value = Mock()
            history.register_request("manual", serving_size=1)

        # Make the entry appear late but within 5x timeout (15 seconds, < 25s)
        entries = history.get_history()
        entries[0]['time_requested'] = datetime.now() - timedelta(seconds=15)

        # Clear the pending job (simulating timeout already fired)
        history._pending_dispense_timeout_job = None

        history.register_zigbee_dispense(portions_dispensed=1, weight_dispensed=50)

        all_entries = history.get_history()
        assert len(all_entries) == 1
        assert all_entries[0]['unit_acknowledged'] is True


class TestTimeoutBehavior:
    """Tests for timeout behavior."""

    def test_timeout_records_error_in_history_entry(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        captured_callback = None
        captured_args = None

        with patch('history.threading.Timer') as mock_timer:
            def capture_timer(timeout, callback, args):
                nonlocal captured_callback, captured_args
                captured_callback = callback
                captured_args = args
                return Mock()

            mock_timer.side_effect = capture_timer
            history.register_request("manual", serving_size=1)

        # Simulate timeout firing
        captured_callback(*captured_args)

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['error'] is not None
        assert "failed to acknowledge" in entries[0]['error']
        assert "5s" in entries[0]['error']

    def test_timeout_clears_pending_job(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        captured_callback = None
        captured_args = None

        with patch('history.threading.Timer') as mock_timer:
            def capture_timer(timeout, callback, args):
                nonlocal captured_callback, captured_args
                captured_callback = callback
                captured_args = args
                return Mock()

            mock_timer.side_effect = capture_timer
            history.register_request("manual", serving_size=1)

        assert history._pending_dispense_timeout_job is not None

        # Simulate timeout firing
        captured_callback(*captured_args)

        assert history._pending_dispense_timeout_job is None

    def test_timeout_with_wrong_event_id_is_ignored(self):
        """If event_id doesn't match (already superseded), timeout is ignored."""
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        captured_callbacks = []

        with patch('history.threading.Timer') as mock_timer:
            def capture_timer(timeout, callback, args):
                captured_callbacks.append((callback, args))
                return Mock()

            mock_timer.side_effect = capture_timer
            # First request
            history.register_request("first", serving_size=1)
            # Acknowledge it
            history._pending_dispense_timeout_job = None
            # Second request (increments event_id)
            history.register_request("second", serving_size=1)

        # First timeout fires (event_id=1) but current is 2
        first_callback, first_args = captured_callbacks[0]
        first_callback(*first_args)

        # First entry should NOT have error (timeout was for old event)
        entries = history.get_history()
        assert entries[0]['error'] is None


class TestRegisterDispense:
    """Tests for register_dispense method (button press, etc)."""

    def test_register_dispense_creates_acknowledged_entry(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        history.register_dispense("Button press", portions_dispensed=1, weight_dispensed=45)

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['source'] == "Button press"
        assert entries[0]['portions_dispensed'] == 1
        assert entries[0]['weight_dispensed'] == 45
        assert entries[0]['unit_acknowledged'] is True
        assert entries[0]['time_acknowledged'] is not None

    def test_register_dispense_with_error(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        history.register_dispense("Unknown", portions_dispensed=1, weight_dispensed=45,
                                  error="Something went wrong")

        entries = history.get_history()
        assert entries[0]['error'] == "Something went wrong"
        assert entries[0]['unit_acknowledged'] is True


class TestScheduleDispenseMethods:
    """Tests for schedule-related dispense methods."""

    def test_register_scheduled_dispense_on_time(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        history.register_scheduled_dispense_on_time(portions_dispensed=2, weight_dispensed=90)

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['source'] == 'Schedule, on-time'
        assert entries[0]['portions_dispensed'] == 2
        assert entries[0]['weight_dispensed'] == 90
        assert entries[0]['unit_acknowledged'] is True
        assert entries[0]['error'] is None

    def test_register_unmatched_scheduled_dispense(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        history.register_unmatched_scheduled_dispense(portions_dispensed=1, weight_dispensed=40)

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['source'] == 'Not in schedule, reported as scheduled'
        assert entries[0]['portions_dispensed'] == 1
        assert entries[0]['error'] is not None
        assert "not expecting" in entries[0]['error'].lower()
        assert entries[0]['unit_acknowledged'] is True

    def test_register_missed_scheduled_dispense(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        history.register_missed_scheduled_dispense(scheduled_hour=8, scheduled_minute=30, tolerance_secs=60)

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['source'] == 'Schedule expected, device missed'
        assert entries[0]['error'] is not None
        assert "8:30" in entries[0]['error']
        assert "60 seconds" in entries[0]['error']
        # Missed schedule is NOT acknowledged (device didn't respond)
        assert entries[0]['unit_acknowledged'] is False


class TestRegisterError:
    """Tests for register_error method."""

    def test_register_error_creates_entry_with_error(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        history.register_error("API", "Connection failed")

        entries = history.get_history()
        assert len(entries) == 1
        assert entries[0]['source'] == "API"
        assert entries[0]['error'] == "Connection failed"
        assert entries[0]['unit_acknowledged'] is False

    def test_register_error_does_not_set_dispense_fields(self):
        history = DispensingHistory("test_feeder", history_len=10, cb_on_dispense=Mock())

        history.register_error("API", "Connection failed")

        entries = history.get_history()
        assert entries[0]['portions_dispensed'] is None
        assert entries[0]['weight_dispensed'] is None
        assert entries[0]['serving_size_requested'] is None
