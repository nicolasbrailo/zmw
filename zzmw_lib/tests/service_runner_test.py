import os
import signal
import unittest
from unittest.mock import patch

from zzmw_lib import service_runner


class TestEarlySigterm(unittest.TestCase):
    def test_sigterm_exits_before_the_service_starts(self):
        handler = signal.getsignal(signal.SIGTERM)
        self.assertTrue(callable(handler))
        with patch.object(service_runner.os, '_exit') as exit_mock:
            handler(signal.SIGTERM, None)
        exit_mock.assert_called_once_with(0)


class TestServiceLogs(unittest.TestCase):
    def _journalctl_args(self, env):
        with patch.dict(os.environ, env, clear=True), \
             patch.object(service_runner.subprocess, 'run') as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = ''
            service_runner.get_this_service_logs()
        return run_mock.call_args[0][0]

    def test_under_systemd_matches_the_invocation(self):
        args = self._journalctl_args({'INVOCATION_ID': 'abc123'})
        self.assertIn('_SYSTEMD_INVOCATION_ID=abc123', args)

    def test_without_systemd_matches_the_pid(self):
        args = self._journalctl_args({})
        self.assertIn(f'_PID={os.getpid()}', args)
