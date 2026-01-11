"""Service monitoring and status tracking."""

import pathlib
import os
import json
import subprocess
import threading
from collections import deque
from datetime import datetime, timedelta

from ansi2html import Ansi2HTMLConverter
from flask import abort, request

from zzmw_lib.zmw_mqtt_mon import ZmwMqttServiceMonitor
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger

from journal_monitor import JournalMonitor

log = build_logger("ZmwServicemon")


class ZmwServicemon(ZmwMqttServiceMonitor):
    """ Monitor other z2m2w services running on this host """

    def __init__(self, cfg, www, sched):
        # Initialize journal monitor (exclude own service to prevent error loops)
        self._journal_monitor = JournalMonitor(
            max_errors=cfg['error_history_len'],
            rate_limit_window_mins=cfg['rate_limit_window_mins'],
            on_error_logged=self._on_service_logged_err,
            own_service_name="zmw_servicemon"
        )

        # Store list of systemd services to monitor from config
        self._systemd_services = cfg.get('systemd_services', [])

        # Track recently sent error messages for deduplication (message_key, timestamp)
        self._recent_messages = deque(maxlen=100)

        # Batch error messages with a 5-second delay
        self._pending_errors = []
        self._error_timer = None
        self._error_lock = threading.Lock()

        # Add configured systemd services to journal monitor
        for service_name in self._systemd_services:
            log.info("Adding configured systemd service '%s' to journal monitor", service_name)
            self._journal_monitor.monitor_unit(service_name)

        super().__init__(cfg, sched)

        www.register_www_dir(os.path.join(pathlib.Path(__file__).parent.resolve(), 'www'))
        www.serve_url('/ls', lambda: json.dumps(dict(sorted(self.get_known_services().items())), default=str))
        www.serve_url('/system_uptime', self.system_uptime)
        www.serve_url('/systemd_status', self.systemd_status)
        www.serve_url('/systemd_services_status', self.systemd_services_status)
        www.serve_url('/systemd_logs', self.systemd_logs)
        www.serve_url('/recent_errors', lambda: json.dumps(self._journal_monitor.get_recent_errors(), default=str))
        www.serve_url('/recent_errors_clear', self._journal_monitor.clear_recent_errors)
        def _log_error():
            log.error("Hola!")
            try:
                raise ValueError(42)
            except ValueError:
                log.error("Exception", exc_info=True)
            return ""
        www.serve_url('/recent_errors_test_new', _log_error)

    def _is_stale(self, last_seen):
        """Check if a service is stale (not seen in the last 5 minutes)."""
        if not last_seen:
            return True
        try:
            # last_seen format: "YYYY-MM-DD HH:mm:ss.microsec"
            last = datetime.fromisoformat(str(last_seen).replace(" ", "T"))
            diff_minutes = (datetime.now() - last).total_seconds() / 60
            return diff_minutes > 5
        except (ValueError, TypeError):
            return True

    def get_service_alerts(self):
        alerts = []
        for svc_name, svc_meta in self.get_known_services().items():
            if self._is_stale(svc_meta.get('last_seen')):
                alerts.append(f"{svc_name} seems down")
        return alerts

    def system_uptime(self):
        return subprocess.run("uptime", stdout=subprocess.PIPE, text=True, check=True).stdout

    def systemd_status(self):
        """Execute services_status.sh script and return HTML-formatted systemd status."""
        status_script = os.path.join(os.getcwd(), '../services_status.sh')
        if not os.path.isfile(status_script):
            script_dir = pathlib.Path(__file__).parent.resolve()
            status_script = script_dir.parent / 'services_status.sh'
            if not status_script.is_file():
                return abort(500, description=f"Can't find status script at {status_script}")
        cmd = str(status_script)
        syslogcmd = subprocess.run(cmd.split(), stdout=subprocess.PIPE, text=True, check=True)
        conv = Ansi2HTMLConverter(inline=True, scheme='ansi2html')
        return conv.convert(syslogcmd.stdout, full=False)

    def systemd_services_status(self):
        """Get status of configured systemd services."""
        services = []
        for service_name in self._systemd_services:
            result = subprocess.run(
                ['systemctl', 'is-active', f'{service_name}.service'],
                capture_output=True, text=True, check=False
            )
            is_running = result.stdout.strip() == 'active'
            services.append({
                'name': service_name,
                'running': is_running,
                'status': result.stdout.strip()
            })
        return json.dumps(services)

    def systemd_logs(self):
        """Get journalctl logs for a specific service."""
        service_name = request.args.get('service')
        if not service_name:
            return abort(400, description="Missing 'service' parameter")

        # Validate service name is in our monitored list for security
        if service_name not in self._systemd_services:
            return abort(403, description=f"Service '{service_name}' is not in the monitored list")

        num_lines = request.args.get('n', '200')

        result = subprocess.run(
            ['journalctl', '-u', f'{service_name}.service', '-n', num_lines, '--no-pager', '-r'],
            capture_output=True, text=True, check=False
        )
        conv = Ansi2HTMLConverter(inline=True, scheme='ansi2html')
        log_content = conv.convert(result.stdout, full=False)
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Logs: {service_name}</title>
    <link rel="stylesheet" href="/zmw.css">
</head>
<body>
    <h1>{service_name} logs</h1>
    <pre>{log_content}</pre>
</body>
</html>'''

    def on_new_svc_discovered(self, svc_name, svc_meta):
        """ Called by ZmwMqttServiceMonitor when a new service is discovered. Not guaranteed that service is alive. """
        journal_name = svc_meta.get('systemd_name', svc_name)
        log.info("New service '%s' with journal '%s' discovered", svc_name, journal_name)
        self._journal_monitor.monitor_unit(journal_name)

    def _on_service_logged_err(self, err):
        msg_key = (err.get('service'), err.get('message'))
        now = datetime.now()

        # Check if this message was sent in the last 7 days
        cutoff = now - timedelta(days=7)
        for i, (sent_key, sent_time) in enumerate(self._recent_messages):
            if sent_key == msg_key and sent_time > cutoff:
                # Message is a duplicate within the last 7 days
                # Refresh timestamp so it will be ignored for another 7 days
                del self._recent_messages[i]
                self._recent_messages.append((msg_key, now))
                return

        self._recent_messages.append((msg_key, now))
        msg = f"{err.get('service')} {err.get('priority_name')}: {err.get('message')}"

        # Batch errors with a 5-second delay, resetting timer on each new error
        with self._error_lock:
            self._pending_errors.append(msg)
            if self._error_timer is not None:
                self._error_timer.cancel()
            self._error_timer = threading.Timer(5.0, self._flush_pending_errors)
            self._error_timer.start()

    def _flush_pending_errors(self):
        """Send all pending error messages combined with newlines."""
        with self._error_lock:
            if not self._pending_errors:
                return
            combined_msg = '\n'.join(self._pending_errors)
            self._pending_errors = []
            self._error_timer = None

        # Bypass service discovery. Because we monitor other services, we don't keep a map of service=>mqtt_topics.
        # I should fix this, but for now this hack will do.
        self.broadcast(f"zmw_telegram/send_text", {'msg': combined_msg, 'topic': 'system error'})

    def stop(self):
        """Stop the service and journal monitor"""
        with self._error_lock:
            if self._error_timer is not None:
                self._error_timer.cancel()
                self._error_timer = None
        self._journal_monitor.stop()
        super().stop()

service_runner(ZmwServicemon)
