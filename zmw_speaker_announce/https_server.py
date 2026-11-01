"""HTTPS proxy server that mirrors endpoints from an HTTP Flask server.

Creates an HTTPS server that exposes the same endpoints as the underlying
HTTP server. Useful when you need HTTPS access for browsers but HTTP access
for devices that can't validate self-signed certificates (like Sonos speakers).
"""
import os
import threading

from flask import Flask, send_from_directory, abort, redirect
from werkzeug.serving import make_server, WSGIRequestHandler

from zzmw_lib.logs import build_logger
from zzmw_lib.network_helpers import get_lan_ip, get_cached_port, is_safe_path

log = build_logger("HttpsServer")


def _get_ssl_context():
    """
    Look for SSL certificate files to enable HTTPS.

    Searches for cert.pem and key.pem in the current directory.

    Returns:
        tuple: (cert_path, key_path) if certs exist, None otherwise
    """
    cert_path = os.path.join(os.getcwd(), 'cert.pem')
    key_path = os.path.join(os.getcwd(), 'key.pem')
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        return None
    return (cert_path, key_path)


class HttpsServer:
    """HTTPS server that proxies endpoint registration to an HTTP Flask app."""

    def __init__(self, http_flask_app, cfg):
        """
        Initialize the HTTPS server as a proxy for an HTTP Flask app.

        If SSL certificates are not found, HTTPS will be disabled but
        endpoint registration will still be proxied to the HTTP server.

        Args:
            http_flask_app: The HTTP Flask app to proxy registrations to
            cfg: Configuration dict with optional 'https_port'
        """
        self._http_app = http_flask_app
        self._cfg = cfg
        self._host = get_lan_ip() or '0.0.0.0'
        self._server = None
        self._thread = None
        self._public_url_base = None
        self._https_app = None

        ssl_context = _get_ssl_context()
        if ssl_context is None:
            log.error("No HTTPS available: cert.pem and key.pem not found in %s", os.getcwd())
            return

        class _QuietRequestHandler(WSGIRequestHandler):
            def log_request(self, *args, **kwargs):
                pass

        self._https_app = Flask("HttpsServer")

        self._server = make_server(
            self._host,
            get_cached_port(cfg, "https_port", self._host),
            self._https_app,
            request_handler=_QuietRequestHandler,
            ssl_context=ssl_context,
            threaded=True
        )

        actual_port = self._server.server_port
        self._public_url_base = f"https://{self._host}:{actual_port}"
        log.info("HTTPS server will be available at %s", self._public_url_base)

    def serve_url(self, url_path, view_func, methods=['GET']):
        """Register a URL endpoint on both HTTP and HTTPS servers."""
        self._http_app.serve_url(url_path, view_func, methods)
        if self._https_app is not None:
            self._https_app.add_url_rule(
                rule=url_path,
                endpoint=url_path,
                view_func=view_func,
                methods=methods)

    def url_cb_ret_none(self, url_path, view_func, methods=['GET', 'PUT']):
        """Register a URL endpoint that returns None on both servers."""
        self._http_app.url_cb_ret_none(url_path, view_func, methods)
        if self._https_app is not None:
            def wrapper(*a, **kw):
                r = view_func(*a, **kw)
                if r is not None:
                    raise ValueError(
                        f'Callback with expected None return actually returned: {str(r)}')
                return {}
            self._https_app.add_url_rule(
                rule=url_path,
                endpoint=url_path,
                view_func=wrapper,
                methods=methods)

    def register_www_dir(self, wwwdir, prefix='/'):
        """Register a directory to serve static files on both servers.

        Returns:
            str: The HTTPS base URL, or HTTP base URL if HTTPS unavailable
        """
        # Register on HTTP server
        self._http_app.register_www_dir(wwwdir, prefix)

        if self._https_app is None:
            return self._http_app.public_url_base

        # Register on HTTPS server
        def srv(filename):
            try:
                safe_path = is_safe_path(wwwdir, filename)
            except ValueError:
                log.warning("Path traversal attempt blocked: %s", filename)
                abort(400, description="Invalid file path")

            if not os.path.isfile(safe_path):
                abort(404, description=f"File {filename} not found")

            return send_from_directory(wwwdir, filename)

        if prefix[-1] != '/' and prefix[0] != '/':
            raise ValueError(
                f"URL prefix needs to start and end with '/'. Received '{prefix}'")
        self._https_app.add_url_rule(f'{prefix}', f'{prefix}',
                                     lambda: redirect(f'{prefix}index.html'))
        self._https_app.add_url_rule(f'{prefix}<path:filename>',
                                     f'{prefix}<path:filename>', srv)

        return self._public_url_base

    def mirror_http_routes(self, paths):
        """Copy existing routes from HTTP server to HTTPS server.

        Use this for routes that were registered on HTTP before HttpsServer
        was created (e.g., /zmw.css, /zmw.js from service_runner).

        Args:
            paths: List of URL paths to mirror (e.g., ['/zmw.css', '/zmw.js'])
        """
        if self._https_app is None:
            return
        for path in paths:
            view_func = self._http_app.view_functions.get(path)
            if view_func:
                self._https_app.add_url_rule(path, path, view_func)
            else:
                log.warning("Cannot mirror route %s: not found in HTTP app", path)

    @property
    def server_url(self):
        """Return the HTTPS base URL, or None if HTTPS unavailable."""
        return self._public_url_base

    def start(self):
        """Start the HTTPS server in a background thread."""
        if self._server is None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def shutdown(self):
        """Shutdown the HTTPS server."""
        if self._server:
            log.info("Shutting down HTTPS server")
            self._server.shutdown()
