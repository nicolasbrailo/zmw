"""MQTT Spotify control service."""
import logging
import os
import pathlib
import requests

from spotipy.oauth2 import SpotifyOauthError
from spotipy.oauth2 import SpotifyOAuth
from spotipy import Spotify as Spotipy
from spotipy import SpotifyException

from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.service_runner import service_runner
from zzmw_lib.logs import build_logger

log = build_logger("ZmwSpotify")

# Suppress noisy spotipy logs
logging.getLogger('spotipy.*').setLevel(logging.INFO)
logging.getLogger('spotipy.oauth2').setLevel(logging.INFO)
logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)
logging.getLogger('spotipy.client').setLevel(logging.CRITICAL)

# A token is valid for an hour, so we refresh every 45 minutes
_SPOTIFY_SECS_BETWEEN_TOK_REFRESH = 60 * 45

def _get_spotify_scopes():
    return 'app-remote-control user-read-playback-state ' \
           'user-modify-playback-state user-read-currently-playing'


def _get_auth_obj(cfg):
    return SpotifyOAuth(
        cfg['client_id'],
        cfg['client_secret'],
        cfg['redirect_uri'],
        scope=_get_spotify_scopes(),
        cache_path=cfg['spotipy_cache'])


def _get_valid_auth_obj(cfg):
    oauth = _get_auth_obj(cfg)
    tok = None if oauth is None else oauth.get_cached_token()
    if tok is None or 'access_token' not in tok or 'refresh_token' not in tok:
        raise RuntimeError('Spotify has no cached token, needs reauth')
    return oauth


def _refresh_access_tok(cfg):
    oauth = _get_valid_auth_obj(cfg)
    refresh_tok = oauth.get_cached_token()['refresh_token']
    new_tok = oauth.refresh_access_token(refresh_tok)
    if new_tok is None:
        raise RuntimeError('Refresh token failed')
    log.debug('Spotify token refresh succeeded')


def _new_spotipy(cfg):
    oauth = _get_valid_auth_obj(cfg).get_cached_token()
    return Spotipy(auth=oauth['access_token'])


class ZmwSpotify(ZmwMqttService):
    """MQTT Spotify control service for playback management."""

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, "zmw_spotify", scheduler=sched)
        self._cfg = cfg
        self._spotipy = None

        # Set up www directory and reauth endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)
        www.serve_url('/reauth', self._serve_reauth_page)
        www.serve_url('/reauth/complete/<code>', self._complete_reauth)
        www.serve_url('/status', self._serve_status_page)

        # Initialize Spotify auth
        try:
            self._refresh_access_tok()
        except (RuntimeError, SpotifyOauthError):
            log.error('Failed to authenticate Spotify, will retry later', exc_info=True)

        # Schedule periodic token refresh
        sched.add_job(
            func=self._refresh_access_tok,
            trigger="interval",
            seconds=_SPOTIFY_SECS_BETWEEN_TOK_REFRESH)

    def _refresh_access_tok(self):
        """Refresh Spotify access token and update the spotipy instance."""
        log.info("Refreshing Spotify access token")
        try:
            _refresh_access_tok(self._cfg)
            self._spotipy = _new_spotipy(self._cfg)
            log.info("Spotify token refresh succeeded")
        except RuntimeError:
            log.error('Failed to authenticate Spotify, needs reauth', exc_info=True)
            self._spotipy = None

    def _serve_reauth_page(self):
        """Serve the OAuth reauthorization page."""
        html = """
        <h1>Spotify Auth Update</h1>
        <ol>
            <li>Go to <a href="{auth_url}" target="blank">this page</a>.
                If asked, accept the permission request from Spotify.</li>
            <li>If approved, you'll be redirected to another page. Copy the URL of this new page.</li>
            <li>
                Paste the URL here: <input type="text" id="redir_url" onChange="validateCode()"/>
                <div id="invalid_code" style="display: inline">
                    That looks like an invalid code! Please try again.
                </div>
            </li>
            <li id="valid_code">
                That looks like a valid code! <a href="#" id="set_new_code_link">Update Spotify token.</a>
            </li>
        </ol>

        <script>
            document.getElementById("valid_code").style.visibility = "hidden";
            document.getElementById("invalid_code").style.visibility = "hidden";

            function validateCode() {{
                var url = document.getElementById("redir_url").value;
                var sep = "?code=";
                var code = url.substr(url.indexOf(sep) + sep.length)
                console.log("Code = ", code);

                if (code.length > 10) {{
                    document.getElementById("invalid_code").style.visibility = "hidden";
                    document.getElementById("valid_code").style.visibility = "visible";
                    document.getElementById("set_new_code_link").href = "{complete_url}" + code;
                }} else {{
                    document.getElementById("invalid_code").style.visibility = "visible";
                    document.getElementById("valid_code").style.visibility = "hidden";
                }}
            }}
        </script>
        """
        return html.format(
            auth_url=_get_auth_obj(self._cfg).get_authorize_url(),
            complete_url=f"{self._public_url_base}/reauth/complete/")

    def _complete_reauth(self, code):
        """Complete the OAuth flow with the provided authorization code."""
        log.info("Starting Spotify reauth with code")
        try:
            _get_auth_obj(self._cfg).get_access_token(code)
            _get_valid_auth_obj(self._cfg)
        except SpotifyOauthError as ex:
            log.error("Spotify reauth failed: %s", ex)
            return str(ex), 400
        except RuntimeError as ex:
            log.error("Spotify reauth failed: %s", ex)
            return str(ex), 400

        self._refresh_access_tok()
        return "Code accepted! Spotify is now authenticated."

    def _serve_status_page(self):
        """Serve the service status page."""
        state = self._get_full_state()

        if not state['is_authenticated']:
            html = """
            <h1>Spotify Service Status</h1>
            <p><strong>Authenticated:</strong> No</p>
            <p><a href="{reauth_url}">Click here to authenticate with Spotify</a></p>
            """
            return html.format(reauth_url=f"{self._public_url_base}/reauth")

        media = state.get('media_info') or {}
        media_html = "<p>No track playing</p>"
        if media:
            media_html = f"""
            <p><strong>Title:</strong> {media['title']}</p>
            <p><strong>Artist:</strong> {media['artist']}</p>
            <p><strong>Album:</strong> <a href="{media['album_link']}">{media['album_name']}</a></p>
            <p><strong>Track:</strong> {media['current_track']} / {media['track_count']}</p>
            <p><strong>Progress:</strong> {media['current_time']:.0f}s / {media['duration']:.0f}s</p>
            """ if media.get('title') else "<p>No track playing</p>"
            if media.get('icon'):
                media_html = f'<p><img src="{media["icon"]}" style="max-width: 200px;"/></p>' + media_html

        html = """
        <h1>Spotify Service Status</h1>
        <p><strong>Authenticated:</strong> Yes</p>
        <p><strong>Playing:</strong> {is_playing}</p>
        <p><strong>Volume:</strong> {volume}%</p>
        <h2>Now Playing</h2>
        {media_html}
        """
        return html.format(
            is_playing="Yes" if state['is_playing'] else "No",
            volume=state['volume'] if state['volume'] is not None else "N/A",
            media_html=media_html)

    def _with_spotify(self, action_name, func, *args):
        """Execute a Spotify action with retry on token expiry."""
        if self._spotipy is None:
            log.warning("Spotify not authenticated, cannot execute %s", action_name)
            return None

        try:
            return func(self._spotipy, *args)
        except requests.exceptions.RequestException as ex:
            log.warning("Spotify request connection failed: %s", ex)
            return None
        except SpotifyException as ex:
            if ex.http_status != 401:
                log.error("Spotify action %s failed: %s", action_name, ex)
                raise
            log.info('Spotify access token expired, refreshing and retrying')
            self._refresh_access_tok()
            if self._spotipy is None:
                return None
            return func(self._spotipy, *args)

    # Spotify action implementations
    def _get_is_playing(self, sp):
        track = sp.current_user_playing_track()
        return (track is not None) and track['is_playing']

    def _stop(self, sp):
        try:
            sp.pause_playback()
        except SpotifyException:
            pass  # Likely already stopped

    def _toggle_play(self, sp):
        if self._get_is_playing(sp):
            self._stop(sp)
        else:
            sp.start_playback()

    def _relative_jump_to_track(self, sp, val):
        val = int(val)
        for _ in range(0, val):
            sp.next_track()
        for _ in range(val, 0):
            sp.previous_track()

    def _get_volume_pct(self, sp):
        active_devices = [d for d in sp.devices()['devices'] if d['is_active']]
        if len(active_devices) == 0:
            return None
        return active_devices[0]['volume_percent']

    def _set_volume_pct(self, sp, volume):
        try:
            sp.volume(int(volume))
        except SpotifyException as ex:
            if ex.http_status == 403:
                log.warning('Setting volume not allowed by Spotify for this device')
                return
            raise

    def _get_media_info(self, sp):
        def pick_album_cover(playback):
            imgs = []
            try:
                imgs = sorted([(img['height'] * img['width'], img['url'])
                               for img in playback['item']['album']['images']])
            except KeyError:
                pass
            selected_img = None
            for img in imgs:
                area, selected_img = img
                if area >= 90000:
                    break
            return selected_img

        def get_context(playback):
            if playback is None or playback.get('context') is None:
                return None
            ctx = playback['context']
            return {
                'type': ctx.get('type'),  # "playlist", "album", "artist", "show"
                'uri': ctx.get('uri'),    # e.g., "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
            }

        playback = sp.current_playback()
        if playback is None or playback.get('item') is None:
            return {}
        return {
            'icon': pick_album_cover(playback),
            'title': playback['item']['name'],
            'duration': playback['item']['duration_ms'] / 1000,
            'current_time': playback['progress_ms'] / 1000,
            'artist': ', '.join([x['name'] for x in playback['item']['album']['artists']]),
            'album_link': playback['item']['album']['external_urls']['spotify'],
            'album_name': playback['item']['album']['name'],
            'track_count': playback['item']['album']['total_tracks'],
            'current_track': playback['item']['track_number'],
            'context': get_context(playback),
        }

    def _get_full_state(self):
        """Get full player state, works even when not authenticated."""
        if self._spotipy is not None:
            try:
                return {
                    'is_authenticated': True,
                    'is_playing': self._with_spotify('is_playing', self._get_is_playing),
                    'volume': self._with_spotify('get_volume', self._get_volume_pct),
                    'media_info': self._with_spotify('get_media_info', self._get_media_info),
                }
            except SpotifyException:
                log.error("Failed to get player state", exc_info=True)

        return {
            'is_authenticated': False,
            'is_playing': False,
            'reauth_url': f"{self._public_url_base}/reauth",
            'volume': 0,
            'media_info': None,
        }

    def get_mqtt_description(self):
        return {
            "description": "Spotify playback control service. Manages OAuth authentication and provides playback controls (play/pause, stop, volume, track navigation) over MQTT. Exposes current playback state including track metadata and album art.",
            "meta": self.get_service_meta(),
            "commands": {
                "publish_state": {
                    "description": "Request current player state. Response published on 'state'",
                    "params": {}
                },
                "stop": {
                    "description": "Stop playback",
                    "params": {}
                },
                "toggle_play": {
                    "description": "Toggle play/pause",
                    "params": {}
                },
                "next_track": {
                    "description": "Jump to next track",
                    "params": {}
                },
                "prev_track": {
                    "description": "Jump to previous track",
                    "params": {}
                },
                "relative_jump_to_track": {
                    "description": "Skip forward or backward N tracks",
                    "params": {"value": "Number of tracks to skip (positive=forward, negative=backward)"}
                },
                "set_volume": {
                    "description": "Set playback volume",
                    "params": {"value": "Volume level 0-100"}
                },
                "get_status": {
                    "description": "Request full player state as JSON. Response published on get_status_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Request MQTT API description. Response published on get_mqtt_description_reply",
                    "params": {}
                },
            },
            "announcements": {
                "state": {
                    "description": "Current player state (response to publish_state)",
                    "payload": {"is_authenticated": "bool", "is_playing": "bool", "volume": "int or null", "media_info": "dict with title, artist, album_name, album_link, icon, duration, current_time, track_count, current_track, context (or null)"}
                },
                "get_status_reply": {
                    "description": "Full player state as JSON (response to get_status)",
                    "payload": {"is_authenticated": "bool", "is_playing": "bool", "volume": "int or null", "media_info": "dict with title, artist, album_name, etc. (or null)", "reauth_url": "string (only when not authenticated)"}
                },
                "get_mqtt_description_reply": {
                    "description": "MQTT API description (response to get_mqtt_description)",
                    "payload": "The get_mqtt_description() dict itself"
                },
            }
        }

    def on_service_received_message(self, subtopic, payload):
        """Handle incoming MQTT messages."""
        if subtopic.endswith('_reply'):
            return

        match subtopic:
            case "publish_state":
                self.publish_own_svc_message("state", self._get_full_state())
            case "stop":
                log.info("Received stop command")
                self._with_spotify('stop', self._stop)
            case "toggle_play":
                log.info("Received toggle_play command")
                self._with_spotify('toggle_play', self._toggle_play)
            case "next_track":
                log.info("Jumping to next track")
                self._with_spotify('relative_jump', self._relative_jump_to_track, 1)
            case "prev_track":
                log.info("Jumping to prev track")
                self._with_spotify('relative_jump', self._relative_jump_to_track, -1)
            case "relative_jump_to_track":
                if 'value' not in payload:
                    log.error("relative_jump_to_track requires 'value' in payload")
                    return
                log.info("Jumping %s tracks", payload['value'])
                self._with_spotify('relative_jump', self._relative_jump_to_track, payload['value'])
            case "set_volume":
                if 'value' not in payload:
                    log.error("set_volume requires 'value' in payload")
                    return
                log.info("Setting volume to %s", payload['value'])
                self._with_spotify('set_volume', self._set_volume_pct, payload['value'])
            case "get_status":
                self.publish_own_svc_message("get_status_reply",
                    self._get_full_state())
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())
            case _:
                # Ignore echo messages
                pass


service_runner(ZmwSpotify)
