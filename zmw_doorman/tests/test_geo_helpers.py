"""Unit tests for geo_helpers.py"""
import pytest
from unittest.mock import patch, Mock
import datetime

from zzmw_lib.geo_helpers import is_sun_out, late_night


class TestIsSunOut:
    """Test is_sun_out function"""

    def setup_method(self):
        """Setup test fixtures"""
        self.lat = 45.0
        self.lon = 9.0
        self.tolerance_mins = 45

    def _create_mock_sun_data(self, sunrise_hour, sunrise_min, sunset_hour, sunset_min, tz=None):
        """Helper to create mock sun data with specific sunrise/sunset times"""
        if tz is None:
            tz = datetime.timezone.utc
        today = datetime.date.today()
        return {
            'sunrise': datetime.datetime(today.year, today.month, today.day, sunrise_hour, sunrise_min, tzinfo=tz),
            'sunset': datetime.datetime(today.year, today.month, today.day, sunset_hour, sunset_min, tzinfo=tz),
            'dusk': datetime.datetime(today.year, today.month, today.day, sunset_hour + 1, sunset_min, tzinfo=tz),
        }

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_is_sun_out_false_within_tolerance_after_sunrise(self, mock_astral_sun, mock_datetime):
        """is_sun_out correctly returns False $tolerance minutes after sunrise"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, tz)

        # Test at 06:30 - only 30 mins after sunrise, within 45 min tolerance
        # Sun is considered "out" only after sunrise + tolerance (06:45)
        current_time = datetime.datetime(today.year, today.month, today.day, 6, 30, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time

        result = is_sun_out(self.lat, self.lon, tolerance_mins=45)

        # Should be False because 06:30 < 06:45 (sunrise + tolerance)
        assert result is False

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_is_sun_out_true_after_tolerance_from_sunrise(self, mock_astral_sun, mock_datetime):
        """is_sun_out correctly returns True after tolerance minutes past sunrise"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, tz)

        # Test at 07:00 - 60 mins after sunrise, past 45 min tolerance
        current_time = datetime.datetime(today.year, today.month, today.day, 7, 0, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time

        result = is_sun_out(self.lat, self.lon, tolerance_mins=45)

        # Should be True because 07:00 > 06:45 (sunrise + tolerance)
        assert result is True

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_is_sun_out_false_within_tolerance_before_sunset(self, mock_astral_sun, mock_datetime):
        """is_sun_out correctly returns False $tolerance minutes before sundown"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, tz)

        # Test at 19:30 - only 30 mins before sunset, within 45 min tolerance
        # Sun is considered "out" only before sunset - tolerance (19:15)
        current_time = datetime.datetime(today.year, today.month, today.day, 19, 30, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time

        result = is_sun_out(self.lat, self.lon, tolerance_mins=45)

        # Should be False because 19:30 > 19:15 (sunset - tolerance)
        assert result is False

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_is_sun_out_true_before_tolerance_from_sunset(self, mock_astral_sun, mock_datetime):
        """is_sun_out correctly returns True before tolerance minutes from sunset"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, tz)

        # Test at 19:00 - 60 mins before sunset, before 45 min tolerance window
        current_time = datetime.datetime(today.year, today.month, today.day, 19, 0, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time

        result = is_sun_out(self.lat, self.lon, tolerance_mins=45)

        # Should be True because 19:00 < 19:15 (sunset - tolerance)
        assert result is True

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_is_sun_out_midnight_transition_before_midnight(self, mock_astral_sun, mock_datetime):
        """is_sun_out behaves correctly at 23:59 (just before midnight)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, tz)

        # Test at 23:59 - well after sunset
        current_time = datetime.datetime(today.year, today.month, today.day, 23, 59, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time

        result = is_sun_out(self.lat, self.lon, tolerance_mins=45)

        # Should be False because it's after sunset
        assert result is False

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_is_sun_out_midnight_transition_after_midnight(self, mock_astral_sun, mock_datetime):
        """is_sun_out behaves correctly at 00:01 (just after midnight)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, tz)

        # Test at 00:01 - well before sunrise
        current_time = datetime.datetime(today.year, today.month, today.day, 0, 1, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time

        result = is_sun_out(self.lat, self.lon, tolerance_mins=45)

        # Should be False because it's before sunrise
        assert result is False


class TestLateNight:
    """Test late_night function"""

    def setup_method(self):
        """Setup test fixtures"""
        self.latlon = (45.0, 9.0)
        self.late_night_start_hour = 23

    def _create_mock_sun_data(self, sunrise_hour, sunrise_min, sunset_hour, sunset_min, dusk_hour, dusk_min, tz=None, base_date=None):
        """Helper to create mock sun data with specific sunrise/sunset/dusk times"""
        if tz is None:
            tz = datetime.timezone.utc
        if base_date is None:
            base_date = datetime.date.today()
        return {
            'sunrise': datetime.datetime(base_date.year, base_date.month, base_date.day, sunrise_hour, sunrise_min, tzinfo=tz),
            'sunset': datetime.datetime(base_date.year, base_date.month, base_date.day, sunset_hour, sunset_min, tzinfo=tz),
            'dusk': datetime.datetime(base_date.year, base_date.month, base_date.day, dusk_hour, dusk_min, tzinfo=tz),
        }

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_late_night_true_after_start_hour(self, mock_astral_sun, mock_datetime):
        """late_night correctly returns True if it's after the specified time (eg 23)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00, dusk at 21:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, 21, 0, tz)

        # Test at 23:30 - after late_night_start_hour (23)
        current_time = datetime.datetime(today.year, today.month, today.day, 23, 30, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time
        mock_datetime.datetime.now.side_effect = [current_time, Mock(hour=23)]

        result = late_night(self.latlon, late_night_start_hour=23)

        # Should be True because it's after 23:00 and after dusk
        assert result is True

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_late_night_true_at_2359(self, mock_astral_sun, mock_datetime):
        """late_night correctly returns True at 23:59 (transition between day and next)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00, dusk at 21:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, 21, 0, tz)

        # Test at 23:59
        current_time = datetime.datetime(today.year, today.month, today.day, 23, 59, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time
        mock_datetime.datetime.now.side_effect = [current_time, Mock(hour=23)]

        result = late_night(self.latlon, late_night_start_hour=23)

        # Should be True because it's after 23:00 and after dusk
        assert result is True

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_late_night_true_at_0001(self, mock_astral_sun, mock_datetime):
        """late_night correctly returns True at 00:01 (transition between day and next)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sun data is from "yesterday" - sunrise at 06:00, sunset at 20:00, dusk at 21:00
        # This simulates querying sun data when it's after midnight
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, 21, 0, tz, base_date=yesterday)

        # Test at 00:01 today - after midnight but before sunrise
        current_time = datetime.datetime(today.year, today.month, today.day, 0, 1, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time
        mock_datetime.datetime.now.side_effect = [current_time, Mock(hour=0)]

        result = late_night(self.latlon, late_night_start_hour=23)

        # Should be True because 0 <= next_sunrise.hour (6)
        assert result is True

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_late_night_remains_true_until_sunrise(self, mock_astral_sun, mock_datetime):
        """late_night remains True until is_sun_out returns True (i.e., until sunrise)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sun data is from "yesterday" - sunrise at 06:00, sunset at 20:00, dusk at 21:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, 21, 0, tz, base_date=yesterday)

        # Test at 05:30 today - just before sunrise, should still be late_night
        current_time = datetime.datetime(today.year, today.month, today.day, 5, 30, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time
        mock_datetime.datetime.now.side_effect = [current_time, Mock(hour=5)]

        result = late_night(self.latlon, late_night_start_hour=23)

        # Should be True because 5 <= next_sunrise.hour (6)
        assert result is True

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_late_night_false_after_sunrise(self, mock_astral_sun, mock_datetime):
        """late_night returns False after sunrise (when sun is out)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00, dusk at 21:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, 21, 0, tz)

        # Test at 10:00 - well after sunrise
        current_time = datetime.datetime(today.year, today.month, today.day, 10, 0, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time
        mock_datetime.datetime.now.side_effect = [current_time, Mock(hour=10)]

        result = late_night(self.latlon, late_night_start_hour=23)

        # Should be False because current time < dusk (it's daytime)
        assert result is False

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_late_night_false_before_late_night_start_hour(self, mock_astral_sun, mock_datetime):
        """late_night is False when is_sun_out is False, and it's before the late_night_start_hour"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00, dusk at 21:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, 21, 0, tz)

        # Test at 22:00 - after dusk but before late_night_start_hour (23)
        current_time = datetime.datetime(today.year, today.month, today.day, 22, 0, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time
        mock_datetime.datetime.now.side_effect = [current_time, Mock(hour=22)]

        result = late_night(self.latlon, late_night_start_hour=23)

        # Should be False because 22 < 23 (late_night_start_hour) and 22 > 6 (next_sunrise.hour)
        assert result is False

    @patch('zzmw_lib.geo_helpers.datetime')
    @patch('zzmw_lib.geo_helpers.astral_sun')
    def test_late_night_false_before_dusk(self, mock_astral_sun, mock_datetime):
        """late_night is False when it's before dusk (even if after sunset)"""
        tz = datetime.timezone.utc
        today = datetime.date.today()
        mock_datetime.date.today.return_value = today
        mock_datetime.timedelta = datetime.timedelta

        # Sunrise at 06:00, sunset at 20:00, dusk at 21:00
        mock_astral_sun.return_value = self._create_mock_sun_data(6, 0, 20, 0, 21, 0, tz)

        # Test at 20:30 - after sunset but before dusk
        current_time = datetime.datetime(today.year, today.month, today.day, 20, 30, tzinfo=tz)
        mock_datetime.datetime.now.return_value = current_time

        result = late_night(self.latlon, late_night_start_hour=23)

        # Should be False because current time < dusk
        assert result is False
