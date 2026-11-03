"""Client for ZmwMeteoRelay, the house's Open-Meteo cache.

The relay is found through service discovery: add METEO_RELAY_SVC to your service's svc_deps, then call
get_weather_from_relay(self, ...). The reply is the Open-Meteo /v1/forecast response, verbatim.

Over HTTP rather than MQTT: get_weather_reply is shared by every client of the relay, so an HTTP request is the
simplest way to be sure the reply is ours.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

METEO_RELAY_SVC = 'ZmwMeteoRelay'

# The relay may block on a fetch from Open-Meteo for a location it doesn't know yet (30s timeout on its side)
_DEFAULT_TIMEOUT_SECS = 45


class MeteoRelayError(RuntimeError):
    """The relay isn't known, can't be reached, or has no data for the location."""


def get_relay_url(svc):
    """Base URL of the relay, as announced over service discovery. None if it isn't known (yet)."""
    meta = svc.get_known_services().get(METEO_RELAY_SVC)
    return meta.get('www') if meta else None


def get_weather_from_relay(svc, lat=None, lon=None, client=None, timeout=_DEFAULT_TIMEOUT_SECS):
    """Weather for (lat, lon), or for the relay's default location if they're None.

    Args:
        svc: A ZmwMqttService with METEO_RELAY_SVC in its svc_deps.
        client: Name to show in the relay's UI (defaults to this host's IP there).

    Raises:
        MeteoRelayError on any failure.
    """
    base_url = get_relay_url(svc)
    if not base_url:
        raise MeteoRelayError(f"{METEO_RELAY_SVC} not discovered (not running, or not in svc_deps?)")
    return get_weather_from_relay_url(base_url, lat, lon, client, timeout)


def get_weather_from_relay_url(base_url, lat=None, lon=None, client=None, timeout=_DEFAULT_TIMEOUT_SECS):
    """As get_weather_from_relay, but with an explicit relay base URL (eg http://10.0.0.10:1234)."""
    if (lat is None) != (lon is None):
        raise ValueError("Need both lat and lon, or neither for the default location")
    path = '/weather' if lat is None else f'/weather/{float(lat)}/{float(lon)}'
    url = base_url.rstrip('/') + path
    if client:
        url += '?' + urllib.parse.urlencode({'client': client})

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode('utf-8'))
            reason = f"{err.get('error')} (last error: {err.get('last_error')})"
        except Exception:  # pylint: disable=broad-except
            reason = e.reason
        raise MeteoRelayError(f"{url}: HTTP {e.code}: {reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MeteoRelayError(f"Can't reach meteo relay at {url}: {e}") from e

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise MeteoRelayError(f"{url}: invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise MeteoRelayError(f"{url}: response is not a JSON object")
    return data
