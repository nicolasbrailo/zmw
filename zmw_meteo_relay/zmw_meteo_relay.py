"""Open-Meteo relay: one cache for every weather client in the house."""

import collections
import json
import os
import pathlib
import threading
from datetime import datetime

from flask import Response, request

from zzmw_lib.logs import build_logger
from zzmw_lib.runtime_state_cache import runtime_state_cache_get, runtime_state_cache_set
from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService

from meteo_cache import MeteoCache, OpenMeteoFetcher, parse_latlon

log = build_logger("ZmwMeteoRelay")

_STATE_CACHE_KEY = 'meteo_relay_known_locations'
_MAX_KNOWN_CLIENTS = 10

# Superset of what the current clients need (zmw_sensormon, zmw_homeboard, AstroDock). Every client gets the same
# cached report, so ask for everything any of them may read. Override with `open_meteo_params` in config.json.
_DEFAULT_OPEN_METEO_PARAMS = {
    'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,'
               'weather_code,cloud_cover,wind_speed_10m,wind_direction_10m',
    'hourly': 'temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,'
              'weather_code,wind_speed_10m',
    'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,'
             'wind_speed_10m_max,sunrise,sunset',
    'forecast_days': 3,
    'timezone': 'auto',
}


class KnownClients:
    """The last N distinct clients that requested weather info."""

    def __init__(self, maxlen):
        self._maxlen = maxlen
        self._clients = collections.OrderedDict()
        self._lock = threading.Lock()

    def seen(self, transport, client_id, user_agent, location):
        key = (transport, client_id)
        with self._lock:
            entry = self._clients.pop(key, None) or {'transport': transport, 'client': client_id, 'request_count': 0}
            entry['request_count'] += 1
            entry['user_agent'] = user_agent
            entry['last_seen_at'] = datetime.now().isoformat(timespec='seconds')
            entry['last_location_id'] = location.id
            entry['last_location'] = {'lat': location.lat, 'lon': location.lon}
            self._clients[key] = entry
            while len(self._clients) > self._maxlen:
                self._clients.popitem(last=False)

    def get(self):
        """Most recent first."""
        with self._lock:
            return [dict(e) for e in reversed(self._clients.values())]


class ZmwMeteoRelay(ZmwMqttService):
    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_meteo_relay", scheduler=sched)

        try:
            default_latlon = parse_latlon(cfg['default_location']['lat'], cfg['default_location']['lon'])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("config.json needs a valid default_location: {\"lat\": ..., \"lon\": ...}") from e

        self._update_interval_minutes = cfg.get('update_interval_minutes', 30)
        fetcher = OpenMeteoFetcher(cfg.get('open_meteo_url', 'https://api.open-meteo.com/v1/forecast'),
                                   cfg.get('open_meteo_params', _DEFAULT_OPEN_METEO_PARAMS))
        self._cache = MeteoCache(
            fetch_fn=fetcher,
            scheduler=sched,
            default_latlon=default_latlon,
            update_interval_secs=int(self._update_interval_minutes * 60),
            dedup_radius_km=cfg.get('dedup_radius_km', 20.0),
            max_locations=cfg.get('max_known_locations', 20),
            retry_base_secs=cfg.get('retry_base_secs', 30),
            persisted=runtime_state_cache_get(_STATE_CACHE_KEY),
            persist_fn=lambda locs: runtime_state_cache_set(_STATE_CACHE_KEY, locs),
            on_update=self._announce_weather_updated,
        )
        self._clients = KnownClients(_MAX_KNOWN_CLIENTS)

        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/weather', self._http_weather_default)
        www.serve_url('/weather/<lat>/<lon>', self._http_weather)
        www.serve_url('/status', self._http_status)

        self._cache.start()

    def get_mqtt_description(self):
        return {
            "description": "Caching relay for Open-Meteo forecasts. Clients ask for the default location or a "
                           "lat/lon; nearby requests share one cached report, refreshed every "
                           f"{self._update_interval_minutes} minutes. Replies carry the Open-Meteo response verbatim.",
            "meta": self.get_service_meta(),
            # MQTT data flow; feeds the map in the top-level README (scripts/build_mqtt_map.py).
            "reads_mqtt_topic": [],
            "writes_mqtt_topic": [],
            "commands": {
                "get_weather": {
                    "description": "Get the weather report for a location (default location if lat/lon are "
                                   "omitted). Response on get_weather_reply",
                    "params": {"lat?": "Latitude", "lon?": "Longitude",
                               "client?": "Name of the requester, shown in the UI and echoed in the reply"},
                },
                "get_known_locations": {
                    "description": "List known locations and their fetch status. Response on "
                                   "get_known_locations_reply",
                    "params": {},
                },
            },
            "announcements": {
                "weather_updated": {
                    "description": "A new report was fetched from Open-Meteo for a known location (periodic "
                                   "update, retry, or a new location). Subscribe to this instead of polling",
                    "payload": {"location": "Known location: {id, lat, lon, is_default}",
                                "fetched_at": "When the report was fetched from Open-Meteo",
                                "weather": "Open-Meteo forecast response, verbatim"},
                },
                "get_weather_reply": {
                    "description": "Weather report. `weather` is the Open-Meteo response verbatim, or null if no "
                                   "data is available (see `error`)",
                    "payload": {"lat": "Requested latitude (null for default)",
                                "lon": "Requested longitude (null for default)",
                                "client": "Echo of the requester's client name",
                                "location": "Known location serving the request: {id, lat, lon, is_default}",
                                "fetched_at": "When the report was fetched from Open-Meteo",
                                "weather": "Open-Meteo forecast response",
                                "error?": "Set if no data is available"},
                },
                "get_known_locations_reply": {
                    "description": "Known locations",
                    "payload": [{"id": "Location id", "lat": "Latitude", "lon": "Longitude",
                                 "is_default": "True for the default location", "fetched_at": "Last good fetch",
                                 "last_error": "Last fetch error, null if healthy"}],
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {"commands": {}, "announcements": {}}
                },
            }
        }

    # ---- HTTP ----

    def _http_weather_default(self):
        return self._http_serve(None, None)

    def _http_weather(self, lat, lon):
        try:
            lat, lon = parse_latlon(lat, lon)
        except ValueError as e:
            return self._json({'error': str(e)}, 400)
        return self._http_serve(lat, lon)

    def _http_serve(self, lat, lon):
        loc = self._cache.get_location_for_request(lat, lon)
        client_id = request.args.get('client') or request.remote_addr
        self._clients.seen('http', client_id, request.headers.get('User-Agent'), loc)
        if loc.weather is None:
            return self._json({'error': 'No weather data available yet', 'last_error': loc.last_error}, 503)
        resp = self._json(loc.weather, 200)
        if loc.fetched_at is not None:
            resp.headers['X-Meteo-Relay-Fetched-At'] = loc.fetched_at.isoformat(timespec='seconds')
        resp.headers['X-Meteo-Relay-Location'] = f"{loc.lat},{loc.lon}"
        return resp

    def _http_status(self):
        return self._json({
            'update_interval_minutes': self._update_interval_minutes,
            'known_locations': [l.summary(with_weather=True) for l in self._cache.get_locations()],
            'known_clients': self._clients.get(),
        }, 200)

    @staticmethod
    def _json(obj, status):
        return Response(json.dumps(obj), status=status, mimetype='application/json')

    # ---- MQTT ----

    @staticmethod
    def _location_ref(loc):
        return {'id': loc.id, 'lat': loc.lat, 'lon': loc.lon, 'is_default': loc.is_default}

    def _announce_weather_updated(self, loc):
        self.publish_own_svc_message("weather_updated", {
            'location': self._location_ref(loc),
            'fetched_at': loc.fetched_at.isoformat(timespec='seconds'),
            'weather': loc.weather,
        })

    def on_service_received_message(self, subtopic, payload):
        if subtopic.endswith('_reply'):
            return
        match subtopic:
            case "get_weather":
                # Off the MQTT thread: a new location means a blocking fetch
                threading.Thread(target=self._on_mqtt_get_weather, args=(payload or {},), daemon=True).start()
            case "get_known_locations":
                self.publish_own_svc_message("get_known_locations_reply",
                                             [l.summary() for l in self._cache.get_locations()])
            case "weather_updated":
                # Self-echo of our own announcement
                pass
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply", self.get_mqtt_description())
            case _:
                log.warning("Ignoring unknown message '%s'", subtopic)

    def _on_mqtt_get_weather(self, msg):
        if not isinstance(msg, dict):
            msg = {}
        client = msg.get('client')
        lat, lon = msg.get('lat'), msg.get('lon')
        reply = {'lat': lat, 'lon': lon, 'client': client, 'location': None, 'fetched_at': None, 'weather': None}

        if (lat is None) != (lon is None):
            reply['error'] = 'Need both lat and lon, or neither for the default location'
            self.publish_own_svc_message("get_weather_reply", reply)
            return
        if lat is not None:
            try:
                lat, lon = parse_latlon(lat, lon)
            except ValueError as e:
                reply['error'] = str(e)
                self.publish_own_svc_message("get_weather_reply", reply)
                return

        loc = self._cache.get_location_for_request(lat, lon)
        self._clients.seen('mqtt', client or 'unnamed', None, loc)
        reply['location'] = self._location_ref(loc)
        reply['weather'] = loc.weather
        if loc.weather is None:
            reply['error'] = f"No weather data available yet: {loc.last_error}"
        elif loc.fetched_at is not None:
            reply['fetched_at'] = loc.fetched_at.isoformat(timespec='seconds')
        self.publish_own_svc_message("get_weather_reply", reply)


service_runner(ZmwMeteoRelay)
