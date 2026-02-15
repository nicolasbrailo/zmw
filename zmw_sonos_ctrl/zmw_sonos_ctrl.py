import os
import signal
import pathlib
import threading
import time

from sonos_helpers import *
import json
import soco
from flask import request
from flask_sock import Sock
from simple_websocket import ConnectionClosed

from zzmw_lib.service_runner import service_runner
from zzmw_lib.zmw_mqtt_service import ZmwMqttService
from zzmw_lib.logs import build_logger

log = build_logger("ZmwSonosCtrl")

class ZmwSonosCtrl(ZmwMqttService):
    """Service to manage Sonos speaker groups and audio source selection."""

    def __init__(self, cfg, www, sched):
        super().__init__(cfg, svc_topic="zmw_sonos_ctrl", scheduler=sched, svc_deps=['ZmwSpotify'])
        self._cfg = cfg

        # Last known coordinator
        self._last_active_coord = None

        # Cache for Spotify state
        self._spotify_context = None
        self._spotify_ready = threading.Event()

        # Track if a hijack request is in progress
        self._hijack_in_progress = threading.Lock()

        # Set up www directory and endpoints
        www_path = os.path.join(pathlib.Path(__file__).parent.resolve(), 'www')
        self._public_url_base = www.register_www_dir(www_path)

        www.serve_url('/get_sonos_play_uris', get_all_sonos_playing_uris)
        www.serve_url('/ls_speakers', lambda: list(ls_speakers().keys()))
        www.serve_url('/world_state', get_all_sonos_state)
        www.serve_url('/stop_all_playback', self._stop_all, methods=['PUT'])
        www.serve_url('/get_spotify_context', self._get_spotify_context)
        www.serve_url('/volume', self._set_volume, methods=['PUT'])
        www.serve_url('/volume_up', self._volume_up, methods=['PUT', 'GET'])
        www.serve_url('/volume_down', self._volume_down, methods=['PUT', 'GET'])
        www.serve_url('/next_track', self._next_track, methods=['PUT', 'GET'])
        www.serve_url('/prev_track', self._prev_track, methods=['PUT', 'GET'])

        # Initialize WebSocket support
        self._sock = Sock(www)
        self._sock.route('/spotify_hijack')(self._ws_spotify_hijack)
        self._sock.route('/line_in_requested')(self._ws_line_in_requested)
        # TODO: Add a WS endpoint to stream updates from Spotify, so it lists the playing media in the UI

    def _build_llm_grammar_values(self):
        state = get_all_sonos_state()
        speakers = state.get('speakers', [])
        if speakers:
            names = sorted(s['speaker_info']['zone_name'] for s in speakers)
            return {'<speaker_name>': names}
        return {}

    def _build_llm_context_extra(self):
        state = get_all_sonos_state()
        speakers = state.get('speakers', [])
        if not speakers:
            return ''
        names = sorted(s['speaker_info']['zone_name'] for s in speakers)
        return "Speakers: " + ', '.join(names)

    def get_mqtt_description(self):
        return {
            "description": "Manage Sonos speakers. Discover network, create groups, control group "\
                           "(redirect Spotify to Sonos, playback: volume, track skip, play/pause). Commands apply to active group.",
            "meta": self.get_service_meta(),
            "sonos_state": get_all_sonos_state(),
            "llm_context_extra": self._build_llm_context_extra(),
            "llm_grammar_values": self._build_llm_grammar_values(),
            "commands": {
                "prev_track": {
                    "description": "Prev track",
                    "params": {}
                },
                "next_track": {
                    "description": "Next track",
                    "params": {}
                },
                "volume_up": {
                    "description": "raise volume",
                    "params": {"vol?": "Step percentage, default 5"}
                },
                "volume_down": {
                    "description": "lower volume",
                    "params": {"vol?": "Step percentage, default 5"}
                },
                "spotify_hijack": {
                    "description": "Move Spotify playback to set of Sonos speakers",
                    "params": {"<speaker_name>": {"vol?": "level (0-100)"}}
                },
                "spotify_hijack_or_toggle_play": {
                    "description": "If playing, pause. If paused, resume. Otherwise, start a new Spotify hijack",
                    "params": {"<speaker_name>": {"vol?": "level (0-100)"}}
                },
                "stop_all": {
                    "description": "Stop playback, destroy groups",
                    "params": {}
                },
                "world_state": {
                    "description": "Get Sonos network state. Response on world_state_reply",
                    "params": {}
                },
                "ls_speakers": {
                    "description": "List of speaker names. Response on ls_speakers_reply",
                    "params": {}
                },
                "get_sonos_play_uris": {
                    "description": "URIs playing on each speaker. Response on get_sonos_play_uris_reply",
                    "params": {}
                },
                "get_spotify_context": {
                    "description": "Get Spotify context/state. Response on get_spotify_context_reply",
                    "params": {}
                },
                "get_mqtt_description": {
                    "description": "Service description",
                    "params": {}
                },
            },
            "announcements": {
                "world_state_reply": {
                    "description": "Network state",
                    "payload": {"speakers": "List of speaker state", "groups": "Map of coordinator name to member", "zones": "List of zone names"}
                },
                "ls_speakers_reply": {
                    "description": "speaker list",
                    "payload": ["names"]
                },
                "get_sonos_play_uris_reply": {
                    "description": "Currently playing",
                    "payload": {"<speaker_name>": "URI"}
                },
                "get_spotify_context_reply": {
                    "description": "Spotify info with context URI and current track",
                    "payload": {"media_info": "dict"}
                },
                "get_mqtt_description_reply": {
                    "description": "Service description",
                    "payload": {"commands": "...", "announcements": "..."}
                },
            }
        }

    def _ws_spotify_hijack(self, ws):
        try:
            # Expected speakers_cfg = {"Baticocina": {"vol": 14}, "BatiDiscos": {"vol": 50}...}
            speakers_cfg = json.loads(ws.receive())
        except ConnectionClosed:
            log.info("WebSocket closed before receiving data")
            return
        except json.JSONDecodeError as ex:
            ws.send(f"Error: Invalid request - {ex}")
            return

        self._do_spotify_hijack(speakers_cfg, ws.send)

    def _spotify_hijack_or_toggle_play(self, speakers_cfg, status_cb=None):
        if status_cb is None:
            status_cb = lambda msg: log.info(msg)

        if not self._last_active_coord:
            return self._do_spotify_hijack(speakers_cfg, status_cb)

        try:
            transport_state = self._last_active_coord.get_current_transport_info()['current_transport_state']
        except soco.exceptions.SoCoException as ex:
            log.warning("Failed to get transport state: %s", ex)
            transport_state = None

        if transport_state == 'PLAYING':
            self._last_active_coord.pause()
            status_cb("Paused playback")
            log.info("Paused playback on %s", self._last_active_coord.player_name)
            return
        elif transport_state == 'PAUSED_PLAYBACK':
            self._last_active_coord.play()
            status_cb("Resumed playback")
            log.info("Resumed playback on %s", self._last_active_coord.player_name)
            return

        # Coordinator reports stopped, or unknown state: assume the user wants to start playback again
        self._do_spotify_hijack(speakers_cfg, status_cb)

    def _do_spotify_hijack(self, speakers_cfg, status_cb=None):
        """Core logic for Spotify hijack, usable from WebSocket or MQTT."""
        if status_cb is None:
            status_cb = lambda msg: log.info(msg)

        if not self._hijack_in_progress.acquire(blocking=False):
            status_cb("Error: A hijack request is already in progress")
            return

        try:
            log.info("User requests to hijack Spotify to %s", speakers_cfg)
            spotify_context = self._get_spotify_context(status_cb)
            spotify_uri = spotify_context.get("media_info", {}).get("context", {}).get("uri") if spotify_context else None
            if spotify_uri is None:
                log.info("User requested Spotify-hijack, but I can't find Spotify playing anything")
                return
            track_num = spotify_context.get("media_info", {}).get("current_track", None)
            # TODO: This gives the track offset from the album, but not from the playlist. For playlists, this will jump at a random spot.
            # zmw_spotify needs to provide a playlist_track_offset and also an album_track_offset
            # TODO: Read magic URI from config
            self._last_active_coord = sonos_hijack_spotify(speakers_cfg, spotify_uri, track_num,
                                                           "sid=9&flags=8232&sn=6", status_cb)
        finally:
            self._hijack_in_progress.release()

    def _get_spotify_context(self, status_cb=None):
        """Get Spotify context, using status_cb to report progress."""
        if status_cb is None:
            status_cb = lambda msg: log.info(msg)
        status_cb("Requesting Spotify state...")
        self._spotify_ready.clear()
        self.message_svc("ZmwSpotify", "publish_state", {})
        if not self._spotify_ready.wait(timeout=5):
            status_cb("Error! Timeout waiting for Spotify state.")
            return "Spotify state timeout. Service is down or unauthenticated"
        return self._spotify_context

    def _ws_line_in_requested(self, ws=None):
        ws.send("UNIMPLEMENTED YET")
        log.error("line-in request not implemented yet")

    def _stop_all(self):
        log.info("Stop-all request: will stop Spotify and reset Sonos states")
        self.message_svc("ZmwSpotify", "stop", {})
        if self._last_active_coord:
            sonos_reset_state_all(self._last_active_coord.group.members, lambda msg: log.info(msg))
        else:
            log.info("No active coordinator found: can't stop")
            # We could also send the stop command to all speakers, but for safety let's limit this to known coordinators
            # log.info("No active coordinator found: sending stop command to ALL speakers")
            # sonos_reset_state_all(ls_speakers().values(), lambda msg: log.info(msg))
        return {}

    def _set_volume(self):
        # This sets the volume of all requested speakers, even if they are not part of the coordinator
        # group. This is because the user needs to manually select the speakers to operate on.
        vol_cfg = request.get_json()
        devs = ls_speakers()
        for spk_name, volume in vol_cfg.items():
            if spk_name in devs:
                devs[spk_name].volume = volume
                log.info("Set %s volume to %s", spk_name, volume)
            else:
                log.warning("Speaker %s not found", spk_name)
        return {}

    def _volume_up(self, vol=5):
        if self._last_active_coord:
            sonos_adjust_volume_all(self._last_active_coord.group.members, vol)
            log.info("Volume up on group %s", self._last_active_coord.player_name)
        else:
            log.info("Volume up requested, but no coordinator known")
        return {}

    def _volume_down(self, vol=5):
        if self._last_active_coord:
            sonos_adjust_volume_all(self._last_active_coord.group.members, -vol)
            log.info("Volume down on group %s", self._last_active_coord.player_name)
        else:
            log.info("Volume down requested, but no coordinator known")
        return {}

    def _next_track(self):
        if self._last_active_coord:
            self._last_active_coord.next()
            log.info("Next track on group %s", self._last_active_coord.player_name)
        else:
            log.info("Next track requested, but no coordinator known")
        return {}

    def _prev_track(self):
        if self._last_active_coord:
            self._last_active_coord.previous()
            log.info("Previous track on group %s", self._last_active_coord.player_name)
        else:
            log.info("Previous track requested, but no coordinator known")
        return {}

    def on_service_received_message(self, subtopic, msg):
        if subtopic.endswith('_reply'):
            return
        # MQTT messages for this service are processed in a background thread, so that we can free up the mqtt thread
        # and reply to other mqtt messages/send other mqtt messages from this service
        threading.Thread(
            target=self._handle_mqtt_message,
            args=(subtopic, msg),
            daemon=True
        ).start()

    def _handle_mqtt_message(self, subtopic, msg):
        match subtopic:
            case "prev_track":
                self._prev_track()
            case "next_track":
                self._next_track()
            case "volume_up":
                self._volume_up(msg.get('vol', 5))
            case "volume_down":
                self._volume_down(msg.get('vol', 5))
            case "spotify_hijack":
                log.info("MQTT request: Spotify hijack")
                self._do_spotify_hijack(msg)
            case "spotify_hijack_or_toggle_play":
                log.info("MQTT request: Spotify hijack or toggle play")
                self._spotify_hijack_or_toggle_play(msg)
            case "stop_all":
                log.info("MQTT request: stop all")
                self._stop_all()
            case "world_state":
                self.publish_own_svc_message("world_state_reply",
                    get_all_sonos_state())
            case "ls_speakers":
                self.publish_own_svc_message("ls_speakers_reply",
                    list(ls_speakers().keys()))
            case "get_sonos_play_uris":
                self.publish_own_svc_message("get_sonos_play_uris_reply",
                    get_all_sonos_playing_uris())
            case "get_spotify_context":
                self.publish_own_svc_message("get_spotify_context_reply",
                    self._get_spotify_context())
            case "get_mqtt_description":
                self.publish_own_svc_message("get_mqtt_description_reply",
                    self.get_mqtt_description())

    def on_dep_published_message(self, svc_name, subtopic, msg):
        """Handle messages from dependent services."""
        if svc_name == "ZmwSpotify" and subtopic == "state":
            if msg is None:
                log.error("Bad message form ZmwSpotify")
                self._spotify_context = {}
                self._spotify_ready.set()
                return
            if "is_authenticated" in msg and not msg["is_authenticated"]:
                log.warning("ZMWSpotify running, but not authenticated")
                self._spotify_context = {}
                self._spotify_ready.set()
                return
            log.info("Received Spotify state")
            self._spotify_context = msg
            spotify_uri = msg.get("media_info", {}).get("context", {}).get("uri")
            if spotify_uri:
                log.info("Spotify published playlist URI: %s", spotify_uri)
            else:
                log.warning("Spotify not playing media, or doesn't expose media URI.")
                log.debug("Received media_info: %s", msg.get("media_info"))
            self._spotify_ready.set()



## XXX    def _switch_to_line_in(self, coordinator, line_in_source=None):
## XXX        """Switch the speaker group to line-in source."""
## XXX        if coordinator is None:
## XXX            log.error("No coordinator to switch to line-in")
## XXX            return False
## XXX        try:
## XXX            if line_in_source:
## XXX                # Play line-in from a specific speaker (e.g., Sonos Port)
## XXX                coordinator.switch_to_line_in(source=line_in_source)
## XXX            else:
## XXX                coordinator.switch_to_line_in()
## XXX            log.info("Switched %s to line-in", coordinator.player_name)
## XXX            return True
## XXX        except soco.exceptions.SoCoException as ex:
## XXX            log.error("Failed to switch to line-in: %s", ex)
## XXX            return False

service_runner(ZmwSonosCtrl)
