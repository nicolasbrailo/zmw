"""Thumbnails of the pictures on the homeboards, fetched from Immich.

A device says which Immich asset is on screen (`id` in its `state/displayed_photo`), but the `src_url` it
publishes needs an API key, so a browser can't load it. This fetches Immich's small thumbnail of an asset with a
key of our own. Only the asset id is taken from the device: the server and key come from our config, so a device
(or a stray retained record) can't make us send the key somewhere else.
"""
import collections
import re
import threading
import urllib.error
import urllib.request

from zzmw_lib.logs import build_logger

log = build_logger("ImmichThumbs")

FETCH_TIMEOUT_SECS = 5
# Immich's "thumbnail" size is ~250px, a few tens of KB; anything this big isn't one
_MAX_THUMB_BYTES = 2 * 1024 * 1024
# Asset ids never change picture, so these never go stale: this only bounds memory
_CACHE_ENTRIES = 32

_ASSET_ID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def as_asset_id(v):
    """The Immich asset id v is, lowercase, or None if it isn't one (it goes into a URL path)."""
    if isinstance(v, str) and _ASSET_ID_RE.match(v):
        return v.lower()
    return None


class ImmichThumbs:
    def __init__(self, url, api_key):
        if not url or not api_key:
            raise ValueError("Immich needs both 'url' and 'api_key'")
        # Immich's API is under /api: accept the server's URL with or without it
        base = url.rstrip('/')
        if not base.endswith('/api'):
            base += '/api'
        self._api = base
        self._api_key = api_key
        self._lock = threading.Lock()
        # asset id -> (bytes, content type), least recently used first
        self._cache = collections.OrderedDict()

    def get(self, asset_id, may_fetch=True):
        """(bytes, content type) of an asset's thumbnail.

        With may_fetch False, only a thumbnail already fetched is returned. Raises ValueError if asset_id isn't an
        asset id, LookupError if Immich has no such asset (or it isn't cached and may_fetch is False),
        RuntimeError if Immich can't be asked or answers something that isn't an image.
        """
        asset_id = as_asset_id(asset_id)
        if asset_id is None:
            raise ValueError("Not an Immich asset id")
        with self._lock:
            hit = self._cache.get(asset_id)
            if hit is not None:
                self._cache.move_to_end(asset_id)
                return hit
        if not may_fetch:
            raise LookupError(f"No thumbnail of {asset_id} fetched")

        # Fetched without the lock, so a slow Immich doesn't hold up cache hits. Two requests for the same new
        # picture may both fetch it, which is harmless.
        thumb = self._fetch(asset_id)
        with self._lock:
            self._cache[asset_id] = thumb
            self._cache.move_to_end(asset_id)
            while len(self._cache) > _CACHE_ENTRIES:
                self._cache.popitem(last=False)
        return thumb

    def _fetch(self, asset_id):
        req = urllib.request.Request(
            f"{self._api}/assets/{asset_id}/thumbnail?size=thumbnail",
            headers={'x-api-key': self._api_key, 'Accept': 'image/*'})
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECS) as resp:
                ctype = resp.headers.get_content_type()
                body = resp.read(_MAX_THUMB_BYTES + 1)
        except urllib.error.HTTPError as e:
            # Immich says 400 for an id it doesn't know, as well as 404
            if e.code in (400, 404):
                raise LookupError(f"Immich has no asset {asset_id}") from e
            raise RuntimeError(f"Immich HTTP {e.code} for asset {asset_id}: {e.reason}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(f"Can't reach Immich: {e}") from e

        if not ctype.startswith('image/'):
            raise RuntimeError(f"Immich sent {ctype} for the thumbnail of {asset_id}, not an image")
        if len(body) > _MAX_THUMB_BYTES:
            raise RuntimeError(f"Immich's thumbnail of {asset_id} is over {_MAX_THUMB_BYTES} bytes")
        log.debug("Fetched thumbnail of %s, %d bytes of %s", asset_id, len(body), ctype)
        return body, ctype
