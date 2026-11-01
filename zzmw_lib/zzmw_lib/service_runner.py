import inspect
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler

from flask import Flask
from flask import send_from_directory, abort, redirect, url_for
from werkzeug.serving import make_server, WSGIRequestHandler

from inotify_simple import INotify, flags
from systemd.journal import JournalHandler

from .zmw_mqtt_base import ZmwMqttBase
from .logs import build_logger
from .network_helpers import get_lan_ip, get_cached_port, is_safe_path

log = build_logger("ServiceRunner")


def _get_http_host(cfg):
    """
    Get the HTTP host to bind to.

    If cfg['http_host'] exists and is not None, use it.
    Otherwise, try to auto-detect the LAN IP.
    If detection fails, fall back to '0.0.0.0'.

    Returns:
        str: The host address to bind to
    """
    if cfg.get('http_host') is not None:
        return cfg['http_host']

    lan_ip = get_lan_ip()
    if lan_ip is not None:
        return lan_ip

    log.error("Could not determine LAN IP, falling back to 0.0.0.0. Service discovery will break.")
    return '0.0.0.0'


def _get_systemd_name(cls):
    # Assume that systemd name is going to be FooBar -> foo_bar
    systemd_name = ''.join(f'_{c.lower()}' if c.isupper() and i > 0 else c.lower() for i, c in enumerate(cls.__name__))

    # Also assume it may be the basename of the dir that contains cls
    class_file = os.path.abspath(inspect.getsourcefile(cls))
    dir_name = os.path.basename(os.path.dirname(class_file))

    result = subprocess.run(['systemctl', 'list-unit-files', f'{systemd_name}.service'],
                            capture_output=True, text=True, check=False)
    if systemd_name in result.stdout:
        return systemd_name
    if dir_name in result.stdout:
        return dir_name

    # Assume it's one of the two, this is likely a dev-service.
    log.warning("Service '%s' will declare '%s' as its systemd/journal name, but it doesn't exist. Things may break", cls.__name__, systemd_name)
    return systemd_name

def _monkeypatch_service_meta(cls, wwwurl):
    # Add get_service_meta to the class before instantiation (in case it's abstract)
    if getattr(getattr(cls, 'get_service_meta', None), '__isabstractmethod__', False):
        systemd_name = _get_systemd_name(cls)
        def _get_service_meta(self):
            return {
                "name": cls.__name__,
                "systemd_name": systemd_name,
                "mqtt_topic": self.get_service_mqtt_topic(),
                "www": wwwurl,
            }
        cls.get_service_meta = _get_service_meta
        # Clear from abstract methods set so ABC allows instantiation
        cls.__abstractmethods__ = cls.__abstractmethods__ - {'get_service_meta'}


def _create_www_server(AppClass, cfg):
    """
    Create Flask app and WSGI server for a service.

    Sets up the Flask application and werkzeug HTTP server.

    Args:
        AppClass: Service class, used for Flask app naming
        cfg: Configuration dict with optional 'http_host' and 'http_port'

    Returns:
        tuple: (flaskapp, wwwserver) where flaskapp has public_url_base set
    """
    class _QuietRequestHandler(WSGIRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_date_time_string(self):
            return ""

        def log_error(self, format, *args):
            # Suppress errors from HTTPS requests hitting HTTP server
            if args:
                msg = str(args)
                if 'Bad request version' in msg or 'Bad HTTP/0.9 request type' in msg:
                    return
            super().log_error(format, *args)

        def log_request(self, code='-', size='-'):
            # Suppress logs for TLS handshake attempts (\x16\x03 is TLS record header)
            if hasattr(self, 'requestline') and self.requestline.startswith('\x16\x03'):
                return
            super().log_request(code, size)

    flaskapp = Flask(AppClass.__name__)
    flaskapp.config['SEND_FILE_MAX_AGE_DEFAULT'] = 7 * 86400 # N days cache for static files

    @flaskapp.after_request
    def set_default_cache_headers(response):
        # If no Cache-Control set (dynamic responses), prevent caching
        if 'Cache-Control' not in response.headers:
            response.headers['Cache-Control'] = 'no-store'
        return response

    http_host = _get_http_host(cfg)
    wwwserver = make_server(http_host,
                            get_cached_port(cfg, "http_port", http_host),
                            flaskapp,
                            request_handler=_QuietRequestHandler,
                            threaded=True)
    flaskapp.public_url_base = f"http://{http_host}:{wwwserver.server_port}"
    log.info("Will serve www requests to %s", flaskapp.public_url_base)
    return flaskapp, wwwserver


def _get_config():
    """ Will open config.json for this service. If the config file doesn't exist, returns an empty map. Will kill the
    running service if the config changes, or if a new config file is created after the service has been started with
    no config file, so the service will have a chance to reload. """
    config_exists = os.path.exists('config.json')

    if config_exists:
        with open('config.json', 'r') as fp:
            cfg = json.loads(fp.read())
    else:
        log.info("Config file config.json not found, using empty config")
        cfg = {}

    def _reload_on_cfg_change():
        inotify = INotify()
        if config_exists:
            inotify.add_watch("config.json", flags.MODIFY)
        else:
            inotify.add_watch(".", flags.CREATE)
        for ev in inotify.read():
            if not config_exists and ev.name != "config.json":
                continue
            log.info("Config file config.json has changed, will reload service (by shutting it down!)")
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(1)
            log.critical("Sent SIGTERM, if you're seeing this something is broken...")

    cfg_checker = threading.Thread(target=_reload_on_cfg_change, daemon=True)
    cfg_checker.start()
    return cfg


def get_this_service_logs():
    """Return logs from the last 24 hours, newest first, as a flask tuple-response"""
    pid = os.getpid()
    try:
        result = subprocess.run([
                'journalctl',
                f'_PID={pid}',
                '--since', '24 hours ago',
                '-r',  # reverse order (newest first)
                '-o', 'json'  # JSON output, one object per line
            ],
            capture_output=True,
            text=True,
            timeout=5
        )
    except subprocess.TimeoutExpired:
        log.error("journalctl command timed out after 5 seconds")
        return {"error": "Log retrieval timed out"}, 504
    except FileNotFoundError:
        log.error("journalctl command not found")
        return {"error": "journalctl not available"}, 503

    if result.returncode != 0:
        log.error("journalctl failed with exit code %d: %s", result.returncode, result.stderr)
        return {"error": "Failed to retrieve logs"}, 500

    logs = []
    for line in result.stdout.strip().split('\n'):
        # Skip flask log lines for user requests, they are too noisy
        if line and not 'werkzeug/_internal.py' in line:
            try:
                logs.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("Failed to parse log line: %s", line[:100])
                continue

    return {"logs": logs, "count": len(logs)}

def service_runner(AppClass):
    """
    Run a service application with embedded Flask web server.

    Loads config.json, sets up Flask server with www directory serving,
    instantiates the service class with Flask app, and runs both with
    proper signal handling for graceful shutdown.

    Args:
        AppClass: Service class to instantiate. Must have __init__(cfg, www)
                  where www is the Flask app with additional methods:
                  - serve_url(path, view_func, methods=['GET'])
                  - register_www_dir(wwwdir, prefix='/')
                  - public_url_base (http://host:port)

    The Flask app runs in a background thread while the main thread
    runs the service's loop_forever().
    """
    cfg = _get_config()
    flaskapp, wwwserver = _create_www_server(AppClass, cfg)

    def serve_url(url_path, view_func, methods=['GET']):
        return flaskapp.add_url_rule(rule=url_path,
                                     endpoint=url_path,
                                     view_func=view_func,
                                     methods=methods)
    def url_cb_ret_none(url_path, view_func, methods=['GET', 'PUT']):
        def wrapper(*a, **kw):
            r = view_func(*a, **kw)
            if r is not None:
                raise ValueError(f'Callback with expected None return actually returned a value: {str(r)}')
            return {}
        return flaskapp.add_url_rule(rule=url_path,
                                     endpoint=url_path,
                                     view_func=wrapper,
                                     methods=methods)

    def register_www_dir(wwwdir, prefix='/'):
        def srv(filename):
            try:
                safe_path = is_safe_path(wwwdir, filename)
            except ValueError as e:
                log.warning(f"Path traversal attempt blocked: {filename}")
                abort(400, description="Invalid file path.")

            if not os.path.isfile(safe_path):
                abort(404, description=f"File {filename} not found")

            try:
                return send_from_directory(wwwdir, filename)
            except Exception as e:
                log.error(f"Error serving file {filename}: {e}")
                return {"error": "Internal server error"}, 500

        if prefix[-1] != '/' and prefix[0] != '/':
            raise ValueError(f"URL prefix needs to start and end with a '/'. Recevied '{prefix}'")
        flaskapp.serve_url(f'{prefix}', lambda: redirect(f'{prefix}index.html'))
        flaskapp.serve_url(f'{prefix}<path:filename>', srv)
        return flaskapp.public_url_base

    www_thread = threading.Thread(target=wwwserver.serve_forever)
    def _www_serve_bg():
        www_thread.start()

    flaskapp.serve_url = serve_url
    flaskapp.url_cb_ret_none = url_cb_ret_none
    flaskapp.register_www_dir = register_www_dir
    flaskapp.startup_automatically = True
    flaskapp.setup_complete = _www_serve_bg

    _lib_www_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'www')
    # Add an endpoint to retrieve logs for this service
    flaskapp.serve_url('/svc_logs', get_this_service_logs)
    flaskapp.serve_url('/svc_logs.html', lambda: send_from_directory(_lib_www_path, 'svc_logs.html'))
    # Add endpoints for common www things
    flaskapp.serve_url('/zmw.css', lambda: send_from_directory(_lib_www_path, 'build/zmw.css'))
    flaskapp.serve_url('/zmw.js', lambda: send_from_directory(_lib_www_path, 'build/zmw.js'))

    if not issubclass(AppClass, ZmwMqttBase):
        raise ValueError("Don't know how to run app '%s', this runner is meant to be used with ZmwMqttServices", AppClass.__name__)

    _monkeypatch_service_meta(AppClass, flaskapp.public_url_base)

    # Create a global scheduler: I've found problems with using too many schedulers, and because this needs to be a
    # reliable mechanism to schedule things (otherwise the service is broken) we'll try to minimize issues that may
    # happen due to concurrency bugs between BG schedulers.
    global_bg_svc_sheduler = BackgroundScheduler()
    global_bg_svc_sheduler.start()

    app = AppClass(cfg, flaskapp, global_bg_svc_sheduler)

    # Add an endpoint to retrieve any alerts that a service can optionally override
    if not hasattr(app, 'get_service_alerts'):
        app.get_service_alerts = lambda: []
    flaskapp.serve_url('/svc_alerts', app.get_service_alerts)

    def signal_handler(sig, frame):
        log.info("Shutdown requested by signal, stop app...")
        wwwserver.shutdown()
        app.stop()
        log.info("Clean exit")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    if flaskapp.startup_automatically:
        # User may override this when the app is instanciated
        flaskapp.setup_complete()
    try:
        app.loop_forever()
    except Exception:  # pylint: disable=broad-except
        # Can't sys.exit: the www thread isn't a daemon, so the process would linger half-dead (no MQTT, scheduler
        # still running) and the service manager would never restart it
        log.critical("MQTT loop died, exiting so the service can be restarted", exc_info=True)
        os._exit(1)
    www_thread.join()
