"""Cache of known locations and their last Open-Meteo report.

Locations are deduplicated by distance: a request close enough to a known location is served from it instead of
creating a new one. Every known location is refreshed periodically. A failed fetch is retried with exponential
backoff, until the next retry would land after the next periodic update; at that point retries stop and the
periodic update takes over.
"""

import itertools
import json
import math
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from zzmw_lib.logs import build_logger

log = build_logger("MeteoCache")

FETCH_TIMEOUT_SECS = 30

_EARTH_RADIUS_KM = 6371.0


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance between two points, in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def parse_latlon(lat, lon):
    """Parse and validate a lat/lon pair (strings or numbers). Raises ValueError if invalid."""
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid coordinates '{lat},{lon}'") from e
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError(f"Invalid coordinates '{lat},{lon}'")
    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude {lat} out of range [-90, 90]")
    if not -180 <= lon <= 180:
        raise ValueError(f"Longitude {lon} out of range [-180, 180]")
    return lat, lon


class OpenMeteoFetcher:
    """Fetches a forecast from Open-Meteo, returning the parsed JSON response verbatim."""

    def __init__(self, api_url, params):
        self._api_url = api_url
        self._params = dict(params)

    def __call__(self, lat, lon):
        params = {**self._params, 'latitude': lat, 'longitude': lon}
        url = f"{self._api_url}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECS) as resp:
                body = resp.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            # Open-Meteo explains bad requests in the body: {"error": true, "reason": "..."}
            try:
                reason = json.loads(e.read().decode('utf-8')).get('reason')
            except Exception:  # pylint: disable=broad-except
                reason = None
            raise RuntimeError(f"Open-Meteo HTTP {e.code}: {reason or e.reason}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(f"Can't reach Open-Meteo: {e}") from e

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Open-Meteo returned invalid JSON: {e}") from e
        if not isinstance(data, dict):
            raise RuntimeError("Open-Meteo returned a non-object response")
        if data.get('error'):
            raise RuntimeError(f"Open-Meteo error: {data.get('reason')}")
        return data


class KnownLocation:
    """A location the relay keeps fresh. Public fields are read under MeteoCache's lock."""

    _ids = itertools.count(1)

    def __init__(self, lat, lon, is_default=False):
        self.id = next(self._ids)
        self.lat = lat
        self.lon = lon
        self.is_default = is_default
        self.created_at = datetime.now()
        self.last_requested_at = None
        self.request_count = 0
        self.weather = None
        self.fetched_at = None
        self.last_attempt_at = None
        self.last_error = None
        self.retry_count = 0
        self.next_retry_at = None
        self.evicted = False
        # Held while fetching, so a location is never fetched twice concurrently. Reentrant: the request that
        # creates a location holds it from creation until its first fetch is done (see MeteoCache._get_or_add)
        self.fetch_lock = threading.RLock()
        self._retry_job = None

    def summary(self, with_weather=False):
        """JSON-able description of this location."""
        s = {
            'id': self.id,
            'lat': self.lat,
            'lon': self.lon,
            'is_default': self.is_default,
            'created_at': _iso(self.created_at),
            'last_requested_at': _iso(self.last_requested_at),
            'request_count': self.request_count,
            'fetched_at': _iso(self.fetched_at),
            'last_attempt_at': _iso(self.last_attempt_at),
            'last_error': self.last_error,
            'retry_count': self.retry_count,
            'next_retry_at': _iso(self.next_retry_at),
        }
        if with_weather:
            s['weather'] = self.weather
        return s

    def to_persisted(self):
        return {
            'lat': self.lat,
            'lon': self.lon,
            'is_default': self.is_default,
            'created_at': _iso(self.created_at),
            'last_requested_at': _iso(self.last_requested_at),
            'request_count': self.request_count,
            'weather': self.weather,
            'fetched_at': _iso(self.fetched_at),
        }

    @classmethod
    def from_persisted(cls, d):
        loc = cls(d['lat'], d['lon'], is_default=d.get('is_default', False))
        loc.created_at = _from_iso(d.get('created_at')) or loc.created_at
        loc.last_requested_at = _from_iso(d.get('last_requested_at'))
        loc.request_count = d.get('request_count', 0)
        loc.weather = d.get('weather')
        loc.fetched_at = _from_iso(d.get('fetched_at'))
        return loc


def _iso(dt):
    return dt.isoformat(timespec='seconds') if dt is not None else None


def _from_iso(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


class MeteoCache:
    """Known locations + periodic refresh with capped exponential backoff."""

    def __init__(self, fetch_fn, scheduler, default_latlon, update_interval_secs=30 * 60,
                 dedup_radius_km=3.0, max_locations=20, retry_base_secs=30,
                 persisted=None, persist_fn=None, on_update=None):
        """
        Args:
            fetch_fn: callable(lat, lon) -> dict. Raises on failure.
            scheduler: APScheduler-like scheduler (add_job with 'interval' and 'date' triggers).
            default_latlon: (lat, lon) of the default location. Never evicted.
            update_interval_secs: Periodic refresh interval for all known locations.
            dedup_radius_km: Requests within this distance of a known location reuse it.
            max_locations: Max known locations; the least recently requested one is evicted beyond this.
            retry_base_secs: First retry delay after a failure; doubles on each consecutive failure.
            persisted: Optional list of KnownLocation.to_persisted() dicts, to restore after a restart.
            persist_fn: Optional callable(list_of_dicts), called when the known locations change.
            on_update: Optional callable(KnownLocation), called after every successful fetch, outside of any lock.
        """
        self._fetch = fetch_fn
        self._sched = scheduler
        self._interval = timedelta(seconds=update_interval_secs)
        self._dedup_radius_km = dedup_radius_km
        self._max_locations = max(1, max_locations)
        self._retry_base_secs = retry_base_secs
        self._persist_fn = persist_fn
        self._on_update = on_update
        self._lock = threading.RLock()
        self._locations = []

        for d in persisted or []:
            try:
                loc = KnownLocation.from_persisted(d)
                loc.is_default = False  # Recomputed below, in case the default changed in config
                self._locations.append(loc)
            except (KeyError, TypeError) as e:
                log.warning("Ignoring bad persisted location %s: %s", d, e)

        dlat, dlon = default_latlon
        default = self._find_nearest(dlat, dlon)
        if default is None:
            default = KnownLocation(dlat, dlon, is_default=True)
            self._locations.insert(0, default)
        default.is_default = True
        self._default = default
        self._trim_locations()

        self._next_periodic_at = datetime.now() + self._interval
        self._sched.add_job(func=self._refresh_all, trigger='interval', seconds=update_interval_secs)

    def start(self):
        """Fetch every known location now, in the background."""
        threading.Thread(target=self._refresh_all_now, daemon=True).start()

    # ---- Queries ----

    def default_location(self):
        return self._default

    def get_locations(self):
        with self._lock:
            return list(self._locations)

    def get_location_for_request(self, lat=None, lon=None):
        """Return the known location serving (lat, lon), or the default one if lat/lon are None.

        A new location is created (and fetched synchronously) if no known one is close enough. If the location
        has no data yet but a fetch is in flight, waits for it. Callers should check `.weather`: it's None if
        there is no data available.
        """
        if lat is None or lon is None:
            loc, is_new = self._default, False
        else:
            loc, is_new = self._get_or_add(lat, lon)

        with self._lock:
            loc.last_requested_at = datetime.now()
            loc.request_count += 1

        if is_new:
            try:
                self.refresh(loc)
            finally:
                loc.fetch_lock.release()
        elif loc.weather is None and loc.fetch_lock.acquire(timeout=FETCH_TIMEOUT_SECS + 5):
            # Startup fetch or a retry may be in flight: wait for it instead of failing straight away
            loc.fetch_lock.release()
        return loc

    # ---- Locations bookkeeping ----

    def _find_nearest(self, lat, lon):
        """Nearest known location within the dedup radius, or None. Must hold lock."""
        best, best_dist = None, None
        for loc in self._locations:
            dist = distance_km(lat, lon, loc.lat, loc.lon)
            if dist <= self._dedup_radius_km and (best_dist is None or dist < best_dist):
                best, best_dist = loc, dist
        return best

    def _get_or_add(self, lat, lon):
        with self._lock:
            loc = self._find_nearest(lat, lon)
            if loc is not None:
                return loc, False
            loc = KnownLocation(lat, lon)
            # Held until the caller's first fetch completes, so concurrent requests for this new location wait for
            # it instead of seeing an empty location. Uncontended: nobody else can see this location yet.
            loc.fetch_lock.acquire()
            self._locations.append(loc)
            log.info("New known location #%d at (%.4f, %.4f)", loc.id, lat, lon)
            self._trim_locations()
            self._persist()
            return loc, True

    def _trim_locations(self):
        """Evict least recently requested locations beyond the cap. Must hold lock."""
        while len(self._locations) > self._max_locations:
            candidates = [l for l in self._locations if not l.is_default]
            if not candidates:
                return
            victim = min(candidates, key=lambda l: l.last_requested_at or l.created_at)
            self._locations.remove(victim)
            victim.evicted = True
            self._cancel_retry(victim)
            log.info("Evicting known location #%d at (%.4f, %.4f), known locations limit is %d",
                     victim.id, victim.lat, victim.lon, self._max_locations)

    def _persist(self):
        """Must hold lock."""
        if self._persist_fn is None:
            return
        try:
            self._persist_fn([l.to_persisted() for l in self._locations])
        except Exception:  # pylint: disable=broad-except
            log.error("Failed to persist known locations", exc_info=True)

    # ---- Refresh and retry ----

    def _refresh_all(self):
        """Periodic update."""
        with self._lock:
            self._next_periodic_at = datetime.now() + self._interval
            locations = list(self._locations)
        min_age = self._interval / 2
        now = datetime.now()
        for loc in locations:
            # A location fetched recently (eg created on demand moments ago) can wait for the next round
            if loc.fetched_at is not None and (now - loc.fetched_at) < min_age and loc.last_error is None:
                continue
            self.refresh(loc)

    def _refresh_all_now(self):
        for loc in self.get_locations():
            self.refresh(loc)

    def refresh(self, loc):
        """Fetch weather for a location. On failure, schedule a retry. Returns True on success."""
        with loc.fetch_lock:
            if loc.evicted:
                return False
            loc.last_attempt_at = datetime.now()
            try:
                data = self._fetch(loc.lat, loc.lon)
            except Exception as e:  # pylint: disable=broad-except
                with self._lock:
                    loc.last_error = str(e)
                    self._schedule_retry(loc)
                return False

            with self._lock:
                loc.weather = data
                loc.fetched_at = datetime.now()
                if loc.last_error is not None:
                    log.info("Location #%d recovered after %d retries", loc.id, loc.retry_count)
                loc.last_error = None
                loc.retry_count = 0
                self._cancel_retry(loc)
                self._persist()

        if self._on_update is not None:
            try:
                self._on_update(loc)
            except Exception:  # pylint: disable=broad-except
                log.error("on_update callback failed for location #%d", loc.id, exc_info=True)
        return True

    def _schedule_retry(self, loc):
        """Must hold lock."""
        self._cancel_retry(loc)
        delay = self._retry_base_secs * (2 ** loc.retry_count)
        retry_at = datetime.now() + timedelta(seconds=delay)
        if retry_at >= self._next_periodic_at:
            log.warning("Fetch for location #%d failed (%s). Next retry would be after the next periodic update "
                        "at %s; stopping retries until then", loc.id, loc.last_error, _iso(self._next_periodic_at))
            # The periodic update starts a new backoff sequence if it fails too
            loc.retry_count = 0
            return
        loc.retry_count += 1
        loc.next_retry_at = retry_at
        log.warning("Fetch for location #%d failed (%s), retry %d in %ds",
                    loc.id, loc.last_error, loc.retry_count, delay)
        loc._retry_job = self._sched.add_job(  # pylint: disable=protected-access
            func=self.refresh, trigger='date', run_date=retry_at, args=[loc])

    def _cancel_retry(self, loc):
        """Must hold lock."""
        # pylint: disable=protected-access
        job, loc._retry_job = loc._retry_job, None
        loc.next_retry_at = None
        if job is None:
            return
        try:
            job.remove()
        except Exception:  # pylint: disable=broad-except
            # Already ran (eg we're inside the retry job itself) or already gone
            pass
