from zzmw_lib.logs import build_logger

from concurrent.futures import ThreadPoolExecutor
from soco.plugins.sharelink import ShareLinkPlugin
import soco
import time
import requests

log = build_logger("ZmwSonosHelpers")

def ls_speakers():
    """Discover all Sonos speakers on the network."""
    speakers = {}
    discovered = soco.discover(timeout=5)
    if discovered:
        for speaker in discovered:
            speakers[speaker.player_name] = speaker
    return speakers

def ls_speaker_filter(names):
    """Get SoCo speaker objects by their names."""
    try:
        all_speakers = ls_speakers()
    except Exception as ex:
        log.error("Failed to discover Sonos speakers", exc_info=True)
        return {}, names

    found = {}
    missing = []
    for name in names:
        if name in all_speakers:
            found[name] = all_speakers[name]
        else:
            missing.append(name)
    return found, missing

def get_all_sonos_playing_uris():
    """ Return all of the URIs being played by all Sonos devices in the network """
    found = {}
    for dev in list(soco.discover()):
        uri = dev.get_current_track_info()['uri']
        name = dev.player_name
        found[name] = uri
    return found

def get_all_sonos_state():
    speakers = []
    groups = {}
    zones = set()
    for spk in list(soco.discover()):
        playing_uri = spk.get_current_track_info().get('uri')
        transport_state = spk.get_current_transport_info().get('current_transport_state')
        try:
            media_info = spk.get_current_media_info()
        except Exception:
            media_info = {}
            log.warning("Failed to parse speaker %s media info", spk.player_name, exc_info=True)
        speakers.append({
                'name': spk.player_name,
                'uri': playing_uri,
                'transport_state': transport_state,
                "volume": spk.volume,
                "is_coordinator": spk.is_coordinator,
                "is_playing_line_in": spk.is_playing_line_in,
                "is_playing_radio": spk.is_playing_radio,
                "is_playing_tv": spk.is_playing_tv,
                'current_media_info': media_info,
                'speaker_info': spk.get_speaker_info(),
        })
        for grp in spk.all_groups:
            if grp.coordinator is None:
                continue
            coord_name = grp.coordinator.player_name
            groups[coord_name] = sorted([m.player_name for m in grp.members])

        for zone in spk.all_zones:
            zones.add(zone.player_name)

    return {
        'speakers': sorted(speakers, key=lambda s: s['name']),
        'groups': dict(sorted(groups.items())),
        'zones': sorted(zones),
    }


def sonos_debug_state(spk, log_fn):
    try:
        actions = spk.avTransport.GetCurrentTransportActions([('InstanceID', 0)])
    except:
        log.warning("Can't retrieve speaker %s actions", spk.player_name, exc_info=True)
        actions = None
    try:
        transport_state = spk.get_current_transport_info()['current_transport_state']
    except:
        log.warning("Can't retrieve speaker %s transport_state", spk.player_name, exc_info=True)
        transport_state = None
    try:
        playing_uri = spk.get_current_track_info()['uri']
    except:
        log.warning("Can't retrieve speaker %s playing_uri", spk.player_name, exc_info=True)
        playing_uri = None

    log_fn(f"State for {spk.player_name}: transport={transport_state} actions={actions} playing={playing_uri}")

def sonos_reset_state(spk, log_fn):
    """ Stops any playback and clears the queue of all speakers in the list. Ignores failures (if a speaker isn't
    playing media, it will throw when trying to stop). Will also remove this speaker from any groups. """
    log_fn(f"Reset config for {spk.player_name}")
    # Attempt to unjoin any speaker groups
    try:
        log_fn(f"Unjoining {spk.player_name} from groups")
        spk.unjoin()
    except soco.exceptions.SoCoException as ex:
        log_fn(f"Failed unjoining {spk.player_name} from groups: {str(ex)}")
        log.warning("Failed unjoining %s from groups", spk.player_name, exc_info=True)
    except requests.exceptions.Timeout:
        log_fn(f"Failed unjoining {spk.player_name} from groups, timeout communicating with speaker")
        log.warning("Failed unjoining %s from groups, timeout", spk.player_name, exc_info=True)
    except requests.exceptions.RequestException:
        log_fn(f"Failed unjoining {spk.player_name} from groups, error communicating with speaker")
        log.warning("Failed unjoining %s from groups, error communicating with speaker", spk.player_name, exc_info=True)

    try:
        spk.stop()
    except:
        pass
    try:
        spk.clear_queue()
    except:
        pass
    try:
        spk.clear_sonos_queue()
    except:
        pass

def sonos_reset_state_all(speakers, log_fn):
    """Reset state for all speakers in parallel."""
    with ThreadPoolExecutor(max_workers=len(speakers)) as executor:
        list(executor.map(lambda spk: sonos_reset_state(spk, log_fn), speakers))

def sonos_adjust_volume(spk, pct):
    """Adjust volume for a speaker. direction: 5 for up %5, -8 for down 8%."""
    try:
        transport_state = spk.get_current_transport_info().get('current_transport_state')
        if transport_state != 'PLAYING':
            return
        current_vol = spk.volume
        direction = 1 if pct > 0 else -1
        min_delta = 2 # The minimum step in volume change, otherwise it will be zero when the volume is low
        delta = max(min_delta, int(current_vol * abs(pct)/100.0)) * direction
        new_vol = max(0, min(100, current_vol + delta))
        spk.volume = new_vol
        log.info("Volume %s %s: %s -> %s", "up" if direction > 0 else "down", spk.player_name, current_vol, new_vol)
    except Exception:
        log.warning("Failed to adjust volume for %s", spk.player_name, exc_info=True)

def sonos_adjust_volume_all(speakers, pct):
    """Adjust volume for all speakers. direction: 5 for up %5, -8 for down 8%."""
    with ThreadPoolExecutor(max_workers=len(speakers)) as executor:
        list(executor.map(lambda spk: sonos_adjust_volume(spk, pct), speakers))

def sonos_reset_and_make_group(speakers_cfg, log_fn):
    """ Receives a map of `speaker_name=>{vol: ##}`. Will look for all speakers with the right name, reset their
    state, and create a group with all the speakers it can.
    Returns a tuple of (coordinator, all_speakers_found, names_of_missing_speakers) """

    search_names = ", ".join(speakers_cfg.keys())
    log_fn(f"Will search LAN for speakers: {search_names}")
    speakers, missing = ls_speaker_filter(speakers_cfg.keys())
    if len(speakers) == 0:
        log_fn("Can't find any speakers, nothing to do")
        return None, None, missing

    # We have at least one speaker
    if missing:
        log_fn(f"Warning! Missing speakers {missing}. Will continue configuring: {speakers.keys()}")
        log.warning("Missing speakers from the network: %s", missing)
    else:
        found_names = ", ".join(speakers.keys())
        log_fn(f"Found: {found_names}")

    sonos_reset_state_all(speakers.values(), log_fn)

    for spk_name, spk in speakers.items():
        try:
            vol = speakers_cfg[spk_name]["vol"]
            spk.volume = vol
            log_fn(f"Set {spk_name} volume to {vol}")
        except soco.exceptions.SoCoException as ex:
            log_fn(f"Failed to set {spk_name} volume: {str(ex)}")
            log.warning("Failed to set %s volume", spk_name, exc_info=True)

    speaker_list = list(speakers.values())
    coord = speaker_list[0]
    log_fn(f"Ready to create speaker group. {coord.player_name} will arbitrarily be the coordinator")
    for spk in speaker_list[1:]:
        try:
            spk.join(coord)
            log_fn(f"{spk.player_name} has joined {coord.player_name}'s party")
        except soco.exceptions.SoCoException as ex:
            log_fn(f"{spk.player_name} failed to join {coord.player_name}'s party: {str(ex)}")
            log.warning("%s failed to join coordinator", spk.player_name, exc_info=True)

    # If there's a single speaker, it will just be the coord, and speakers=[coord]
    return coord, speakers, missing

def sonos_fix_spotify_uris(spotify_uri, sonos_magic_uri, log_fn):
    if spotify_uri is None or len(spotify_uri) == 0:
        log_fn("No Spotify URI, are you playing something? NOTE: tracks don't have a URI, only playlists or discs.")
        return None, None
    else:
        log_fn(f"Received Spotify URI '{spotify_uri}'")

    # spotify:playlist:0nACysarxt7GPofO5tiIiq → https://open.spotify.com/playlist/0nACysarxt7GPofO5tiIiq
    soco_sharelink_uri_parts = spotify_uri.split(':')
    if len(soco_sharelink_uri_parts) == 3:
        soco_sharelink_uri = f"https://open.spotify.com/{soco_sharelink_uri_parts[1]}/{soco_sharelink_uri_parts[2]}"
        log_fn(f"Built soco sharelink uri {soco_sharelink_uri}")
    else:
        soco_sharelink_uri = None
        log_fn("Don't know how to build a soco share link for this URI, things may break")

    # Spotify URIs need to be in the x-sonos-spotify format. Convert spotify:playlist:xxx to the Sonos format
    if spotify_uri.startswith("spotify:"):
        # Format: x-sonos-spotify:spotify:playlist:xxx?sid=X&flags=Y&sn=Z
        # The sid/flags/sn values depend on the Sonos account setup
        alt_spotify_uri = f"x-sonos-spotify:{spotify_uri}?{sonos_magic_uri}"
        log_fn(f"Built alt Spotify URI '{alt_spotify_uri}'")
    else:
        log_fn(f"Warning! The URI is NOT in the expected format, can't build alt-uri")
        alt_spotify_uri = None

    # Sonos needs a set of magic URI params like `?sid=9&flags=8232&sn=6` to work. If the ones the user supplied don't work, then
    # they need to:
    # 1. Play a playlist from the Sonos app (NOT from Spotify, must be a Spotify playlist but from the SONOS app)
    # 2. Use this service to dump all of the URIs of all known devices
    # 3. Hope one of the URIs matches and has the magic numbers.
    log_fn(f"Built Sonos-compatible URIs. Using hardcoded `{sonos_magic_uri}`; if these don't work, start a playlist using the Sonos app, and check all the URIs using this service.")
    return soco_sharelink_uri, alt_spotify_uri

def sonos_sharelink_play(spk, soco_sharelink_uri, track_num, log_fn):
    try:
        sharelink = ShareLinkPlugin(spk)
        sharelink.add_share_link_to_queue(soco_sharelink_uri)
        if track_num is None:
            track_num = 0
        if track_num > 1:
            # Sonos/soco uses 0-based track index
            track_num -= 1
        spk.play_from_queue(track_num)
        log_fn(f"ShareLink play request accepted, starting from track {track_num}")
    except soco.exceptions.SoCoException as ex:
        log_fn(f"ShareLink play request failed: {str(ex)}")
        log.error("Failed to ShareLink play Spotify URI", exc_info=True)

def sonos_wait_transport(spk, timeout, log_fn):
    while timeout > 0:
        timeout = timeout - 1
        try:
            sonos_debug_state(spk, log_fn)
            transport_state = spk.get_current_transport_info()['current_transport_state']
            if transport_state != 'TRANSITIONING':
                break
        except soco.exceptions.SoCoException as ex:
            transport_state = None
            log_fn(f"ShareLink play request failed: {str(ex)}")
            log.error("Failed to ShareLink play Spotify URI", exc_info=True)
        time.sleep(1)
    return transport_state

def sonos_hijack_spotify(speakers_cfg, spotify_uri, track_num, sonos_magic_uri, log_fn):
    soco_sharelink_uri, alt_spotify_uri = sonos_fix_spotify_uris(spotify_uri, sonos_magic_uri, log_fn)
    if not soco_sharelink_uri and not alt_spotify_uri:
        log_fn("No Sonos compatible URIs found, can't continue")
        return None

    coord, speakers, missing = sonos_reset_and_make_group(speakers_cfg, log_fn)
    if not coord:
        log_fn("No leader speaker found, can't continue")
        return None

    def _try_apply(cb):
        cb()
        state = sonos_wait_transport(coord, timeout=5, log_fn=log_fn)
        if state == 'PLAYING':
            log_fn("Sonos reports success")
            return True
        else:
            log_fn(f"Sonos report state={state}, not PLAYING.")
            return False

    def _maybe_apply_track(spk):
        if track_num is not None and track_num > 1:
            try:
                # Sonos/soco uses 0-based track index
                spk.seek(track=track_num-1)
            except soco.exceptions.SoCoException as ex:
                log_fn(f"Can't jump to track {track_num}: {ex}")
                log.error("Failed to jump to track", exc_info=True)

    sonos_debug_state(coord, log_fn)

    if soco_sharelink_uri is not None:
        log_fn(f"Trying to play Sharelink({soco_sharelink_uri})...")
        if _try_apply(lambda: sonos_sharelink_play(coord, soco_sharelink_uri, track_num, log_fn)):
            return coord

    if alt_spotify_uri is not None:
        log_fn(f"Trying alternate play with direct url {alt_spotify_uri}")
        if _try_apply(lambda: coord.play_uri(alt_spotify_uri)):
            _maybe_apply_track(coord)
            return coord

    if soco_sharelink_uri is not None:
        log_fn(f"Trying altalternate play with direct sharelink url {soco_sharelink_uri}")
        if _try_apply(lambda: coord.play_uri(soco_sharelink_uri)):
            _maybe_apply_track(coord)
            return coord

    log_fn("Ran out of things to try: can't hijack Spotify, sorry")
    return None
