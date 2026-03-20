""" UniFi controller API client. """

import requests
import urllib3


class UnsupportedUnifi(Exception):
    pass


class AuthError(Exception):
    pass

urllib3.disable_warnings()

ENDPOINTS = [
    {"login": "/api/login",      "clients": "/api/s/default/stat/sta"},
    {"login": "/api/auth/login", "clients": "/proxy/network/api/s/default/stat/sta"},
]


class UnifiClient:
    def __init__(self, controller, username, password):
        self._controller = controller.rstrip('/')
        self._username = username
        self._password = password
        self._session = None
        self._endpoint = None
        # {mac: {hostname, mac, ip}} — current and previous snapshots for change detection
        self._previous = None
        self._current = {}
        self._all_clients = {}
        # If login fails, make sure we fail early, during service startup
        self._login()

    def _login(self):
        """Authenticate with the controller. Raises on failure."""
        session = requests.Session()
        session.verify = False

        got_auth_error = False
        for ep in ENDPOINTS:
            try:
                login_resp = session.post(f"{self._controller}{ep['login']}", json={
                    "username": self._username,
                    "password": self._password,
                })
            except requests.exceptions.RequestException:
                raise ConnectionError(f"Can't reach UniFi controller at {self._controller}.")
            if login_resp.ok:
                self._session = session
                self._endpoint = ep
                return
            if login_resp.status_code in (401, 403):
                got_auth_error = True
            session.cookies.clear()

        if got_auth_error:
            raise AuthError(f"Invalid credentials for UniFi controller at {self._controller}.")
        raise UnsupportedUnifi(f"Failed to login to UniFi controller at {self._controller} (tried standard + UDM endpoints).")

    def get_all_clients(self):
        """Return the raw list of all connected clients from the controller."""
        resp = self._session.get(f"{self._controller}{self._endpoint['clients']}")
        if resp.status_code == 401:
            self._login()
            resp = self._session.get(f"{self._controller}{self._endpoint['clients']}")
        resp.raise_for_status()
        return resp.json().get("data", [])

    def get_interesting_clients(self, interesting):
        """Return a dict of {mac: {hostname, mac, ip}} for connected interesting devices.

        interesting: a set of hostnames and/or MAC addresses to match against.
        Also updates all_clients with the full unfiltered client list.
        """
        clients = self.get_all_clients()
        all_parsed = {}
        result = {}
        for c in clients:
            hostname = c.get("hostname") or c.get("name") or "(unknown)"
            mac = c.get("mac", "")
            ip = c.get("ip", "(unknown)")
            entry = {"hostname": hostname, "mac": mac, "ip": ip}
            all_parsed[mac] = entry
            if not interesting or hostname in interesting or mac in interesting:
                result[mac] = entry
        self._all_clients = all_parsed
        return result

    def poll_changes(self, interesting):
        """Poll controller, return (joined, left, current) dicts.

        joined: {mac: {hostname, mac, ip}} for newly connected devices
        left: {mac: {hostname, mac, ip}} for disconnected devices (using last known info)
        current: {mac: {hostname, mac, ip}} for all currently connected interesting devices
        Returns (None, None, current) on the first poll (no previous state).
        """
        current = self.get_interesting_clients(interesting)
        current_macs = set(current.keys())

        if self._previous is None:
            # First run, have no previous known state
            self._previous = current
            self._current = current
            return None, None, None

        prev_macs = set(self._previous.keys())
        joined = {mac: current[mac] for mac in current_macs - prev_macs}
        left = {mac: self._previous[mac] for mac in prev_macs - current_macs}

        self._previous = current
        self._current = current
        return joined, left, current

    @property
    def current_clients(self):
        return self._current

    @property
    def all_clients(self):
        """All connected clients (unfiltered) from the last poll."""
        return self._all_clients
