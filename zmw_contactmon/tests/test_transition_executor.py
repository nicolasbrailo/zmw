"""Unit tests for transition_executor.py"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from transition_executor import TransitionExecutor


class TestTransitionExecutor:
    """Test TransitionExecutor class"""

    def setup_method(self):
        """Setup test fixtures"""
        self.cfg = {
            'chime_skip_default_secs': 120,
            'chime_skip_max_secs': 300
        }
        self.scheduler = Mock()
        self.svc_mgr = Mock()
        self.actions = {
            'Sensor1': {
                'open': {
                    'telegram': {'msg': 'Door opened'},
                    'whatsapp': {'msg': 'WA message'}
                },
                'close': {
                    'tts_announce': {'msg': 'Door closed', 'lang': 'en'},
                    'sound_asset_announce': {'public_www': 'http://example.com/sound.mp3'}
                }
            }
        }

        self.executor = TransitionExecutor(
            self.cfg,
            self.scheduler,
            self.svc_mgr,
            self.actions
        )

    def test_telegram_action_executes(self):
        """Test telegram action calls message_svc with correct params"""
        self.executor.on_transition('Sensor1', 'open')

        self.svc_mgr.message_svc.assert_any_call(
            'ZmwTelegram',
            'send_text',
            {'msg': 'Door opened'}
        )

    def test_whatsapp_action_executes(self):
        """Test whatsapp action calls message_svc with correct params"""
        self.executor.on_transition('Sensor1', 'open')

        self.svc_mgr.message_svc.assert_any_call(
            'ZmwWhatsapp',
            'send_text',
            {'msg': 'WA message'}
        )

    def test_tts_announce_action_executes(self):
        """Test tts_announce action calls message_svc with correct params"""
        self.executor.on_transition('Sensor1', 'close')

        self.svc_mgr.message_svc.assert_any_call(
            'ZmwSpeakerAnnounce',
            'tts',
            {'msg': 'Door closed', 'lang': 'en'}
        )

    def test_sound_asset_announce_action_executes(self):
        """Test sound_asset_announce action calls message_svc with correct params"""
        self.executor.on_transition('Sensor1', 'close')

        self.svc_mgr.message_svc.assert_any_call(
            'ZmwSpeakerAnnounce',
            'play_asset',
            {'public_www': 'http://example.com/sound.mp3'}
        )

    def test_all_actions_execute_together(self):
        """Test multiple actions in same transition all execute"""
        self.executor.on_transition('Sensor1', 'open')

        assert self.svc_mgr.message_svc.call_count == 2
        calls = [call[0] for call in self.svc_mgr.message_svc.call_args_list]
        assert ('ZmwTelegram', 'send_text', {'msg': 'Door opened'}) in calls
        assert ('ZmwWhatsapp', 'send_text', {'msg': 'WA message'}) in calls

    def test_telegram_skipped_when_skipping_sms(self):
        """Test telegram action NOT invoked when skipping_sms is True"""
        self.executor._skipping_sms = True

        self.executor.on_transition('Sensor1', 'open')

        # Should not call telegram service
        telegram_calls = [
            call for call in self.svc_mgr.message_svc.call_args_list
            if call[0][0] == 'ZmwTelegram'
        ]
        assert len(telegram_calls) == 0

    def test_whatsapp_skipped_when_skipping_sms(self):
        """Test whatsapp action NOT invoked when skipping_sms is True"""
        self.executor._skipping_sms = True

        self.executor.on_transition('Sensor1', 'open')

        # Should not call whatsapp service
        whatsapp_calls = [
            call for call in self.svc_mgr.message_svc.call_args_list
            if call[0][0] == 'ZmwWhatsapp'
        ]
        assert len(whatsapp_calls) == 0

    def test_tts_announce_skipped_when_skipping_chime(self):
        """Test tts_announce action NOT invoked when skipping_chime is True"""
        self.executor._skipping_chime = True

        self.executor.on_transition('Sensor1', 'close')

        # Should not call tts service
        tts_calls = [
            call for call in self.svc_mgr.message_svc.call_args_list
            if call[0][1] == 'tts'
        ]
        assert len(tts_calls) == 0

    def test_sound_asset_announce_skipped_when_skipping_chime(self):
        """Test sound_asset_announce action NOT invoked when skipping_chime is True"""
        self.executor._skipping_chime = True

        self.executor.on_transition('Sensor1', 'close')

        # Should not call play_asset service
        asset_calls = [
            call for call in self.svc_mgr.message_svc.call_args_list
            if call[0][1] == 'play_asset'
        ]
        assert len(asset_calls) == 0

    def test_mock_mode_skips_all_actions(self):
        """Test mock mode sets both skipping flags and prevents all actions"""
        # Create executor in mock mode
        with patch.object(TransitionExecutor, '__init__', lambda self, cfg, sched, svc, acts: None):
            executor = TransitionExecutor(None, None, None, None)
            executor._svc_mgr = self.svc_mgr
            executor._actions = self.actions
            executor._running_in_mock_mode = True
            executor._skipping_sms = True
            executor._skipping_chime = True

        executor.on_transition('Sensor1', 'open')
        executor.on_transition('Sensor1', 'close')

        # No services should be called
        assert self.svc_mgr.message_svc.call_count == 0

    def test_skip_chimes_with_timeout_default(self):
        """Test skip_chimes_with_timeout disables chimes with default timeout"""
        result = self.executor.skip_chimes_with_timeout()

        assert self.executor._skipping_chime is True
        assert result == {'timeout': 120}
        self.scheduler.add_job.assert_called_once()

        # Verify job scheduled with correct parameters
        call_args = self.scheduler.add_job.call_args
        assert call_args[0][0] == self.executor.enable_chimes
        assert call_args[0][1] == 'date'
        assert 'run_date' in call_args[1]

    def test_skip_chimes_with_timeout_custom(self):
        """Test skip_chimes_with_timeout with custom duration"""
        result = self.executor.skip_chimes_with_timeout(180)

        assert self.executor._skipping_chime is True
        assert result == {'timeout': 180}
        self.scheduler.add_job.assert_called_once()

    def test_skip_chimes_with_timeout_stores_job(self):
        """Test skip_chimes_with_timeout stores scheduled job"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job

        self.executor.skip_chimes_with_timeout(100)

        assert self.executor._chime_skip_job == mock_job

    def test_skip_chimes_with_timeout_invalid_string(self):
        """Test skip_chimes_with_timeout with invalid string aborts"""
        with pytest.raises(Exception):  # abort() raises exception
            self.executor.skip_chimes_with_timeout('invalid')

    def test_skip_chimes_with_timeout_too_small(self):
        """Test skip_chimes_with_timeout with value too small aborts"""
        with pytest.raises(Exception):  # abort() raises exception
            self.executor.skip_chimes_with_timeout(3)

    def test_skip_chimes_with_timeout_too_large(self):
        """Test skip_chimes_with_timeout with value too large aborts"""
        with pytest.raises(Exception):  # abort() raises exception
            self.executor.skip_chimes_with_timeout(500)

    def test_skip_chimes_with_timeout_resets_existing(self):
        """Test skip_chimes_with_timeout resets existing timeout"""
        # Set up first timeout
        mock_job1 = Mock()
        mock_job1.id = 'job1'
        self.scheduler.add_job.return_value = mock_job1
        self.executor.skip_chimes_with_timeout(100)

        # Set up second timeout
        mock_job2 = Mock()
        mock_job2.id = 'job2'
        self.scheduler.add_job.return_value = mock_job2
        self.executor.skip_chimes_with_timeout(150)

        # First job should be removed
        self.scheduler.remove_job.assert_called_once_with('job1')
        # New job should be stored
        assert self.executor._chime_skip_job == mock_job2

    def test_enable_chimes_cancels_skip_job(self):
        """Test enable_chimes cancels pending skip job"""
        # Set up skip job
        mock_job = Mock()
        mock_job.id = 'job1'
        self.scheduler.add_job.return_value = mock_job
        self.executor.skip_chimes_with_timeout(100)

        # Enable chimes
        self.executor.enable_chimes()

        # Job should be removed
        self.scheduler.remove_job.assert_called_once_with('job1')
        assert self.executor._chime_skip_job is None

    def test_enable_chimes_overrides_skip_chimes(self):
        """Test enable_chimes overrides skip_chimes_with_timeout"""
        # Skip chimes
        self.executor.skip_chimes_with_timeout(100)
        assert self.executor._skipping_chime is True

        # Enable chimes
        self.executor.enable_chimes()
        assert self.executor._skipping_chime is False

        # Actions should now execute
        self.executor.on_transition('Sensor1', 'close')
        assert self.svc_mgr.message_svc.call_count > 0

    def test_enable_chimes_when_not_skipping(self):
        """Test enable_chimes when chimes are not being skipped"""
        assert self.executor._skipping_chime is False

        self.executor.enable_chimes()

        # Should not cause errors
        assert self.executor._skipping_chime is False

    def test_get_skipping_chimes_when_not_skipping(self):
        """Test get_skipping_chimes returns False when not skipping"""
        assert self.executor.get_skipping_chimes() is False

    def test_get_skipping_chimes_when_skipping(self):
        """Test get_skipping_chimes returns True when skipping"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job
        self.executor.skip_chimes_with_timeout(100)

        assert self.executor.get_skipping_chimes() is True

    def test_get_skipping_chimes_timeout_secs(self):
        """Test get_skipping_chimes_timeout_secs returns remaining time"""
        # Set up mock job with next_run_time
        mock_job = Mock()
        future_time = datetime.now() + timedelta(seconds=100)
        mock_job.next_run_time = future_time
        self.scheduler.add_job.return_value = mock_job

        self.executor.skip_chimes_with_timeout(100)

        timeout = self.executor.get_skipping_chimes_timeout_secs()
        assert timeout is not None
        assert 95 < timeout <= 100  # Allow some timing variance

    def test_get_skipping_chimes_timeout_secs_when_not_skipping(self):
        """Test get_skipping_chimes_timeout_secs returns None when not skipping"""
        timeout = self.executor.get_skipping_chimes_timeout_secs()
        assert timeout is None

    def test_on_transition_no_action(self):
        """Test on_transition with non-existent action doesn't crash"""
        self.executor.on_transition('Sensor1', 'nonexistent')

        # Should not call any services
        assert self.svc_mgr.message_svc.call_count == 0

    def test_on_transition_empty_action_config(self):
        """Test on_transition with empty action config"""
        self.executor._actions['Sensor1']['open']['telegram'] = None

        self.executor.on_transition('Sensor1', 'open')

        # Should skip None config but still execute whatsapp
        whatsapp_calls = [
            call for call in self.svc_mgr.message_svc.call_args_list
            if call[0][0] == 'ZmwWhatsapp'
        ]
        assert len(whatsapp_calls) == 1

    def test_config_validation_min_greater_than_default(self):
        """Test config validation fails when min > default"""
        bad_cfg = {
            'chime_skip_default_secs': 3,
            'chime_skip_max_secs': 300
        }

        with pytest.raises(ValueError, match="Minimum should be bigger than default"):
            TransitionExecutor(bad_cfg, self.scheduler, self.svc_mgr, self.actions)

    def test_config_validation_default_greater_than_max(self):
        """Test config validation fails when default > max"""
        bad_cfg = {
            'chime_skip_default_secs': 400,
            'chime_skip_max_secs': 300
        }

        with pytest.raises(ValueError, match="default should be less than maximum"):
            TransitionExecutor(bad_cfg, self.scheduler, self.svc_mgr, self.actions)

    def test_enable_chimes_respects_mock_mode(self):
        """Test enable_chimes keeps skipping enabled in mock mode"""
        self.executor._running_in_mock_mode = True
        self.executor._skipping_chime = True

        self.executor.enable_chimes()

        # Should remain True in mock mode
        assert self.executor._skipping_chime is True

    def test_skip_chime_job_cancel_handles_missing_job(self):
        """Test _skip_chime_job_cancel handles job removal gracefully"""
        # Set up job that will fail to remove
        mock_job = Mock()
        mock_job.id = 'job1'
        self.scheduler.remove_job.side_effect = Exception("Job not found")
        self.executor._chime_skip_job = mock_job

        # Should not raise exception
        result = self.executor._skip_chime_job_cancel()

        assert self.executor._chime_skip_job is None
        assert result is False


class TestChimeOverride:
    """Test chime_override functionality"""

    def setup_method(self):
        self.cfg = {
            'chime_skip_default_secs': 120,
            'chime_skip_max_secs': 300
        }
        self.scheduler = Mock()
        self.svc_mgr = Mock()
        self.actions = {
            'Sensor1': {
                'open': {
                    'telegram': {'msg': 'Door opened'},
                },
                'close': {
                    'sound_asset_announce': {'public_www': 'http://example.com/sound.mp3'}
                }
            }
        }
        self.executor = TransitionExecutor(
            self.cfg, self.scheduler, self.svc_mgr, self.actions
        )

    def test_chime_override_registers(self):
        """Test chime_override stores override and returns confirmation"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job

        result = self.executor.chime_override('Sensor1', 'close', 'http://other.com/ding.mp3', 60)

        assert result == {
            'sensor_name': 'Sensor1', 'action': 'close',
            'url': 'http://other.com/ding.mp3', 'timeout': 60
        }
        assert ('Sensor1', 'close') in self.executor._chime_overrides
        assert self.executor._chime_overrides[('Sensor1', 'close')]['url'] == 'http://other.com/ding.mp3'

    def test_chime_override_schedules_cleanup_job(self):
        """Test chime_override schedules a job to remove the override"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job

        self.executor.chime_override('Sensor1', 'close', 'http://other.com/ding.mp3', 60)

        self.scheduler.add_job.assert_called_once()
        call_args = self.scheduler.add_job.call_args
        assert call_args[0][0] == self.executor._remove_chime_override
        assert call_args[0][1] == 'date'
        assert call_args[1]['args'] == [('Sensor1', 'close')]

    def test_chime_override_uses_default_timeout(self):
        """Test chime_override uses default timeout when not specified"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job

        result = self.executor.chime_override('Sensor1', 'close', 'http://other.com/ding.mp3')

        assert result['timeout'] == 120

    def test_chime_override_invalid_timeout(self):
        """Test chime_override rejects invalid timeout"""
        with pytest.raises(Exception):
            self.executor.chime_override('Sensor1', 'close', 'http://x.com/s.mp3', 'bad')

    def test_chime_override_timeout_too_small(self):
        """Test chime_override rejects timeout below minimum"""
        with pytest.raises(Exception):
            self.executor.chime_override('Sensor1', 'close', 'http://x.com/s.mp3', 3)

    def test_chime_override_timeout_too_large(self):
        """Test chime_override rejects timeout above maximum"""
        with pytest.raises(Exception):
            self.executor.chime_override('Sensor1', 'close', 'http://x.com/s.mp3', 500)

    def test_chime_override_replaces_existing(self):
        """Test chime_override replaces an existing override for same key"""
        mock_job1 = Mock()
        mock_job1.id = 'job1'
        self.scheduler.add_job.return_value = mock_job1
        self.executor.chime_override('Sensor1', 'close', 'http://first.com/a.mp3', 60)

        mock_job2 = Mock()
        mock_job2.id = 'job2'
        self.scheduler.add_job.return_value = mock_job2
        self.executor.chime_override('Sensor1', 'close', 'http://second.com/b.mp3', 90)

        # Old job cancelled
        self.scheduler.remove_job.assert_called_once_with('job1')
        # New override stored
        assert self.executor._chime_overrides[('Sensor1', 'close')]['url'] == 'http://second.com/b.mp3'

    def test_sound_asset_uses_override_url(self):
        """Test on_transition uses override URL instead of configured asset"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job
        self.executor.chime_override('Sensor1', 'close', 'http://override.com/chime.mp3', 60)

        self.executor.on_transition('Sensor1', 'close')

        self.svc_mgr.message_svc.assert_called_once_with(
            'ZmwSpeakerAnnounce', 'play_asset', {'public_www': 'http://override.com/chime.mp3'}
        )

    def test_sound_asset_uses_config_without_override(self):
        """Test on_transition uses configured asset when no override exists"""
        self.executor.on_transition('Sensor1', 'close')

        self.svc_mgr.message_svc.assert_called_once_with(
            'ZmwSpeakerAnnounce', 'play_asset',
            {'public_www': 'http://example.com/sound.mp3'}
        )

    def test_override_persists_across_multiple_triggers(self):
        """Test override is used on repeated triggers until it expires"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job
        self.executor.chime_override('Sensor1', 'close', 'http://override.com/chime.mp3', 60)

        self.executor.on_transition('Sensor1', 'close')
        self.executor.on_transition('Sensor1', 'close')

        assert self.svc_mgr.message_svc.call_count == 2
        for call in self.svc_mgr.message_svc.call_args_list:
            assert call[0] == ('ZmwSpeakerAnnounce', 'play_asset', {'public_www': 'http://override.com/chime.mp3'})

    def test_remove_chime_override(self):
        """Test _remove_chime_override cleans up the override"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job
        self.executor.chime_override('Sensor1', 'close', 'http://override.com/chime.mp3', 60)

        self.executor._remove_chime_override(('Sensor1', 'close'))

        assert ('Sensor1', 'close') not in self.executor._chime_overrides

    def test_remove_chime_override_nonexistent_key(self):
        """Test _remove_chime_override with nonexistent key does not crash"""
        self.executor._remove_chime_override(('NoSensor', 'nope'))

    def test_override_does_not_affect_other_actions(self):
        """Test override on one action does not affect other actions for same sensor"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job
        self.executor.chime_override('Sensor1', 'open', 'http://override.com/chime.mp3', 60)

        # 'close' should still use configured asset
        self.executor.on_transition('Sensor1', 'close')

        self.svc_mgr.message_svc.assert_called_once_with(
            'ZmwSpeakerAnnounce', 'play_asset',
            {'public_www': 'http://example.com/sound.mp3'}
        )

    def test_override_skipped_when_chimes_skipped(self):
        """Test override is not used when chimes are globally skipped"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job
        self.executor.chime_override('Sensor1', 'close', 'http://override.com/chime.mp3', 60)
        self.executor._skipping_chime = True

        self.executor.on_transition('Sensor1', 'close')

        assert self.svc_mgr.message_svc.call_count == 0

    def test_after_override_expires_uses_config(self):
        """Test that after override is removed, config asset is used again"""
        mock_job = Mock()
        self.scheduler.add_job.return_value = mock_job
        self.executor.chime_override('Sensor1', 'close', 'http://override.com/chime.mp3', 60)

        # Simulate expiry
        self.executor._remove_chime_override(('Sensor1', 'close'))

        self.executor.on_transition('Sensor1', 'close')
        self.svc_mgr.message_svc.assert_called_once_with(
            'ZmwSpeakerAnnounce', 'play_asset',
            {'public_www': 'http://example.com/sound.mp3'}
        )
