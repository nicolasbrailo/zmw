import os
import signal
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from zzmw_lib.z2m.networks_health import Z2MNetworksHealth

# The startup check SIGTERMs the process when a network is missing. Tests that expect it patch os.kill; anywhere
# else, fail the test instead of killing the test runner.
_os_kill_guard = patch('zzmw_lib.z2m.networks_health.os.kill',
                       side_effect=AssertionError('Z2MNetworksHealth tried to kill the process'))

def setUpModule():
    _os_kill_guard.start()

def tearDownModule():
    _os_kill_guard.stop()


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, trigger, kwargs))


T0 = datetime(2026, 1, 1, 12, 0, 0)


class TestZ2MNetworksHealth(unittest.TestCase):
    def setUp(self):
        self.sched = FakeScheduler()
        with patch('zzmw_lib.z2m.networks_health.datetime') as fake_dt:
            fake_dt.now.return_value = T0
            self.health = Z2MNetworksHealth(['net_a', 'net_b'], self.sched)

    def _startup_check(self):
        self.sched.jobs[0][0]()

    def _publish_all(self):
        for topic in ('net_a', 'net_b'):
            self.health.on_message(topic)
            self.health.on_devices_published(topic)

    def test_schedules_startup_check(self):
        self.assertEqual(len(self.sched.jobs), 1)
        _, trigger, kwargs = self.sched.jobs[0]
        self.assertEqual(trigger, 'date')
        self.assertEqual(kwargs['run_date'], T0 + timedelta(seconds=3))

    def test_custom_timeouts(self):
        sched = FakeScheduler()
        with patch('zzmw_lib.z2m.networks_health.datetime') as fake_dt:
            fake_dt.now.return_value = T0
            health = Z2MNetworksHealth(['net_a'], sched, startup_timeout_secs=10, ping_timeout_minutes=2)
        self.assertEqual(sched.jobs[0][2]['run_date'], T0 + timedelta(seconds=10))
        health.on_devices_published('net_a')
        sched.jobs[0][0]()
        self.assertEqual(sched.jobs[1][2]['minutes'], 2)

    def test_missing_networks(self):
        self.assertEqual(self.health.missing_networks(), ['net_a', 'net_b'])
        self.health.on_devices_published('net_b')
        self.assertEqual(self.health.missing_networks(), ['net_a'])
        self.health.on_devices_published('net_a')
        self.assertEqual(self.health.missing_networks(), [])

    def test_messages_dont_count_as_published_devices(self):
        self.health.on_message('net_a')
        self.assertEqual(self.health.missing_networks(), ['net_a', 'net_b'])

    @patch('zzmw_lib.z2m.networks_health.os.kill')
    def test_startup_check_kills_if_a_network_is_missing(self, kill):
        self.health.on_devices_published('net_a')
        with self.assertLogs('Z2M', level='CRITICAL') as logs:
            self._startup_check()
        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        self.assertIn("'net_b'", logs.output[0])
        self.assertNotIn("'net_a'", logs.output[0])
        self.assertEqual(len(self.sched.jobs), 1)

    def test_startup_check_schedules_stale_check(self):
        self._publish_all()
        self._startup_check()
        self.assertEqual(len(self.sched.jobs), 2)
        _, trigger, kwargs = self.sched.jobs[1]
        self.assertEqual(trigger, 'interval')
        self.assertEqual(kwargs['minutes'], 5)
        self.assertEqual(kwargs['id'], self.health.health_check_job_id)

    def test_health_check_job_id_is_readable(self):
        job_id = self.health.health_check_job_id
        self.assertTrue(job_id.startswith('z2m_health_check_'), job_id)
        self.assertTrue(job_id.endswith('[net_a,net_b]'), job_id)

    def test_health_check_job_ids_are_unique(self):
        # APScheduler rejects duplicate job IDs, and two instances in one process would have the same topics
        other = Z2MNetworksHealth(['net_a', 'net_b'], self.sched)
        self.assertNotEqual(self.health.health_check_job_id, other.health_check_job_id)

    def _stale_check_at(self, last_msgs, check_at_minute):
        """ Both networks publish at minute 0; last_msgs is {topic: minute} of later messages """
        with patch('zzmw_lib.z2m.networks_health.datetime') as fake_dt:
            fake_dt.now.return_value = T0
            self._publish_all()
            self._startup_check()
            for topic, minute in last_msgs.items():
                fake_dt.now.return_value = T0 + timedelta(minutes=minute)
                self.health.on_message(topic)
            fake_dt.now.return_value = T0 + timedelta(minutes=check_at_minute)
            self.sched.jobs[1][0]()

    def test_stale_check_quiet_when_all_networks_recent(self):
        with self.assertNoLogs('Z2M', level='ERROR'):
            self._stale_check_at({'net_a': 8, 'net_b': 9}, check_at_minute=10)

    def test_stale_check_names_only_the_stale_network(self):
        with self.assertLogs('Z2M', level='ERROR') as logs:
            self._stale_check_at({'net_a': 8}, check_at_minute=10)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("'net_b'", logs.output[0])

    def test_stale_check_reports_every_stale_network(self):
        with self.assertLogs('Z2M', level='ERROR') as logs:
            self._stale_check_at({}, check_at_minute=10)
        self.assertEqual(len(logs.output), 2)


if __name__ == '__main__':
    unittest.main()
