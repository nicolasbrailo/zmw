"""Unit tests for door_stats.py"""
import pytest
from unittest.mock import Mock, patch

from door_stats import DoorStats, DoorbellPressRecord, MotionEventRecord, DoorOpenRecord


@pytest.fixture(autouse=True)
def mock_cache():
    """Mock runtime_state_cache functions for all tests."""
    with patch('door_stats.runtime_state_cache_get', return_value=None), \
         patch('door_stats.runtime_state_cache_set'):
        yield


class TestDoorStats:
    """Test DoorStats class"""

    def setup_method(self):
        """Setup test fixtures"""
        self.scheduler = Mock()

    def test_init_schedules_nightly_reset(self):
        """Verify nightly reset job is scheduled at midnight"""
        stats = DoorStats(self.scheduler)

        self.scheduler.add_job.assert_called_once()
        call_kwargs = self.scheduler.add_job.call_args[1]
        assert call_kwargs['id'] == 'door_stats_nightly_reset'
        # Verify it's a CronTrigger for midnight
        trigger = call_kwargs['trigger']
        assert trigger.fields[5].name == 'hour'  # hour field
        assert str(trigger.fields[5]) == '0'
        assert trigger.fields[6].name == 'minute'  # minute field
        assert str(trigger.fields[6]) == '0'

    def test_record_doorbell_press_increments_counter(self):
        """Doorbell press increments daily counter"""
        stats = DoorStats(self.scheduler)

        assert stats._doorbell_press_count_today == 0
        stats.record_doorbell_press()
        assert stats._doorbell_press_count_today == 1
        stats.record_doorbell_press()
        assert stats._doorbell_press_count_today == 2

    def test_record_doorbell_press_stores_history(self):
        """Doorbell press is stored in history with timestamp and snap_path"""
        stats = DoorStats(self.scheduler)

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 1000.0
            stats.record_doorbell_press('/path/to/snap1.jpg')

        assert len(stats._doorbell_presses) == 1
        record = stats._doorbell_presses[0]
        assert record.timestamp == 1000.0
        assert record.snap_path == '/path/to/snap1.jpg'

    def test_record_doorbell_press_updates_last_snap_path(self):
        """Doorbell press with snap_path updates last_snap_path"""
        stats = DoorStats(self.scheduler)

        stats.record_doorbell_press('/path/to/snap.jpg')
        assert stats._last_snap_path == '/path/to/snap.jpg'

    def test_record_doorbell_press_without_snap_does_not_update_last_snap(self):
        """Doorbell press without snap_path does not update last_snap_path"""
        stats = DoorStats(self.scheduler)
        stats._last_snap_path = '/existing/snap.jpg'

        stats.record_doorbell_press(None)
        assert stats._last_snap_path == '/existing/snap.jpg'

    def test_doorbell_history_limited_to_10(self):
        """Doorbell history is limited to last 10 entries"""
        stats = DoorStats(self.scheduler)

        for i in range(15):
            stats.record_doorbell_press(f'/snap{i}.jpg')

        assert len(stats._doorbell_presses) == 10
        # First entries should be gone, last 10 remain
        assert stats._doorbell_presses[0].snap_path == '/snap5.jpg'
        assert stats._doorbell_presses[9].snap_path == '/snap14.jpg'

    def test_record_motion_start_increments_counter(self):
        """Motion start increments daily counter"""
        stats = DoorStats(self.scheduler)

        assert stats._motion_detection_count_today == 0
        stats.record_motion_start()
        assert stats._motion_detection_count_today == 1
        stats.record_motion_end()
        stats.record_motion_start()
        assert stats._motion_detection_count_today == 2

    def test_record_motion_start_and_end_stores_duration(self):
        """Motion event records duration when ended"""
        stats = DoorStats(self.scheduler)

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 1000.0
            stats.record_motion_start()

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 1005.5
            stats.record_motion_end()

        assert len(stats._motion_events) == 1
        record = stats._motion_events[0]
        assert record.start_time == 1000.0
        assert record.duration_secs == 5.5

    def test_record_motion_end_without_start_is_noop(self):
        """Motion end without start does nothing"""
        stats = DoorStats(self.scheduler)

        stats.record_motion_end()  # Should not raise
        assert len(stats._motion_events) == 0

    def test_motion_history_limited_to_10(self):
        """Motion history is limited to last 10 entries"""
        stats = DoorStats(self.scheduler)

        for i in range(15):
            with patch('door_stats.time') as mock_time:
                mock_time.time.return_value = float(i * 100)
                stats.record_motion_start()
            with patch('door_stats.time') as mock_time:
                mock_time.time.return_value = float(i * 100 + 10)
                stats.record_motion_end()

        assert len(stats._motion_events) == 10
        # First entries should be gone, last 10 remain
        assert stats._motion_events[0].start_time == 500.0
        assert stats._motion_events[9].start_time == 1400.0

    def test_record_door_open_and_close_stores_duration(self):
        """Door open/close records duration"""
        stats = DoorStats(self.scheduler)

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 2000.0
            stats.record_door_open()

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 2003.0
            stats.record_door_close()

        assert len(stats._door_open_events) == 1
        record = stats._door_open_events[0]
        assert record.start_time == 2000.0
        assert record.duration_secs == 3.0

    def test_record_door_close_without_open_is_noop(self):
        """Door close without open does nothing"""
        stats = DoorStats(self.scheduler)

        stats.record_door_close()  # Should not raise
        assert len(stats._door_open_events) == 0

    def test_record_door_open_twice_closes_previous(self):
        """Opening door twice auto-closes previous event"""
        stats = DoorStats(self.scheduler)

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 1000.0
            stats.record_door_open()

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 1005.0
            stats.record_door_open()  # Should close previous

        assert len(stats._door_open_events) == 1
        assert stats._door_open_events[0].duration_secs == 5.0

    def test_door_history_limited_to_10(self):
        """Door open history is limited to last 10 entries"""
        stats = DoorStats(self.scheduler)

        for i in range(15):
            with patch('door_stats.time') as mock_time:
                mock_time.time.return_value = float(i * 100)
                stats.record_door_open()
            with patch('door_stats.time') as mock_time:
                mock_time.time.return_value = float(i * 100 + 5)
                stats.record_door_close()

        assert len(stats._door_open_events) == 10
        assert stats._door_open_events[0].start_time == 500.0
        assert stats._door_open_events[9].start_time == 1400.0

    def test_record_snap_updates_last_snap_path(self):
        """record_snap updates last_snap_path"""
        stats = DoorStats(self.scheduler)

        stats.record_snap('/new/snap.jpg')
        assert stats._last_snap_path == '/new/snap.jpg'

        stats.record_snap('/newer/snap.jpg')
        assert stats._last_snap_path == '/newer/snap.jpg'

    def test_nightly_reset_clears_counters(self):
        """Nightly reset clears daily counters but keeps history"""
        stats = DoorStats(self.scheduler)

        # Record some events
        stats.record_doorbell_press('/snap.jpg')
        stats.record_doorbell_press('/snap2.jpg')
        stats.record_motion_start()
        stats.record_motion_end()
        stats.record_motion_start()
        stats.record_motion_end()
        stats.record_motion_start()
        stats.record_motion_end()

        assert stats._doorbell_press_count_today == 2
        assert stats._motion_detection_count_today == 3

        # Trigger nightly reset
        stats._nightly_reset()

        # Counters should be reset
        assert stats._doorbell_press_count_today == 0
        assert stats._motion_detection_count_today == 0

        # History should be preserved
        assert len(stats._doorbell_presses) == 2
        assert len(stats._motion_events) == 3

    def test_get_stats_returns_all_data(self):
        """get_stats returns complete statistics dictionary"""
        stats = DoorStats(self.scheduler)

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 1000.0
            stats.record_doorbell_press('/snap1.jpg')

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 2000.0
            stats.record_motion_start()
        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 2010.0
            stats.record_motion_end()

        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 3000.0
            stats.record_door_open()
        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 3005.0
            stats.record_door_close()

        result = stats.get_stats()

        assert result['doorbell_press_count_today'] == 1
        assert result['motion_detection_count_today'] == 1
        assert result['last_snap'] == 'snap1.jpg'
        assert len(result['doorbell_presses']) == 1
        assert result['doorbell_presses'][0]['timestamp'] == 1000.0
        assert result['doorbell_presses'][0]['snap'] == 'snap1.jpg'
        assert len(result['motion_events']) == 1
        assert result['motion_events'][0]['start_time'] == 2000.0
        assert result['motion_events'][0]['duration_secs'] == 10.0
        assert len(result['door_open_events']) == 1
        assert result['door_open_events'][0]['start_time'] == 3000.0
        assert result['door_open_events'][0]['duration_secs'] == 5.0
        assert result['motion_in_progress'] is False
        assert result['door_open_in_progress'] is False

    def test_get_stats_shows_in_progress_events(self):
        """get_stats shows when motion or door events are in progress"""
        stats = DoorStats(self.scheduler)

        stats.record_motion_start()
        result = stats.get_stats()
        assert result['motion_in_progress'] is True
        assert result['door_open_in_progress'] is False

        stats.record_door_open()
        result = stats.get_stats()
        assert result['motion_in_progress'] is True
        assert result['door_open_in_progress'] is True

        stats.record_motion_end()
        result = stats.get_stats()
        assert result['motion_in_progress'] is False
        assert result['door_open_in_progress'] is True


class TestVisitorRecords:
    """Visitor notifications in the door history"""

    def test_record_visitor_in_history_and_counter(self):
        stats = DoorStats(Mock())
        with patch('door_stats.time') as mock_time:
            mock_time.time.return_value = 1000.0
            stats.record_visitor("Belen is at the door", "doorbell_20261122_104507")
        res = stats.get_stats()
        assert res["visitor_count_today"] == 1
        assert res["history"] == [{"event_type": "visitor", "time": 1000.0, "msg": "Belen is at the door",
                                   "session_id": "doorbell_20261122_104507"}]

    def test_visitors_persisted_and_restored(self):
        with patch('door_stats.runtime_state_cache_set') as cache_set:
            DoorStats(Mock()).record_visitor("Someone is at the door", "s1")
            saved = cache_set.call_args[0][1]
        saved["counters_date"] = __import__('datetime').date.today().isoformat()
        with patch('door_stats.runtime_state_cache_get', return_value=saved):
            restored = DoorStats(Mock()).get_stats()
        assert restored["visitor_count_today"] == 1
        assert restored["visitors"][0]["msg"] == "Someone is at the door"
        assert restored["visitors"][0]["session_id"] == "s1"

    def test_nightly_reset_clears_visitor_count(self):
        stats = DoorStats(Mock())
        stats.record_visitor("Someone is at the door", "s1")
        stats._nightly_reset()
        assert stats.get_stats()["visitor_count_today"] == 0
        assert len(stats.get_stats()["visitors"]) == 1


class TestDataClasses:
    """Test dataclass definitions"""

    def test_doorbell_press_record_defaults(self):
        """DoorbellPressRecord has correct defaults"""
        record = DoorbellPressRecord(timestamp=1000.0)
        assert record.timestamp == 1000.0
        assert record.snap_path is None

    def test_motion_event_record_defaults(self):
        """MotionEventRecord has correct defaults"""
        record = MotionEventRecord(start_time=1000.0)
        assert record.start_time == 1000.0
        assert record.duration_secs is None

    def test_door_open_record_defaults(self):
        """DoorOpenRecord has correct defaults"""
        record = DoorOpenRecord(start_time=1000.0)
        assert record.start_time == 1000.0
        assert record.duration_secs is None
