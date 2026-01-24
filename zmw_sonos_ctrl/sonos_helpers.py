from zzmw_lib.logs import build_logger

from concurrent.futures import ThreadPoolExecutor, wait
from soco.plugins.sharelink import ShareLinkPlugin
import soco
import time
import requests

log = build_logger("ZmwSonosHelpers")

# Set timeout for all SoCo HTTP requests to speakers (default is None/no timeout)
soco.config.REQUEST_TIMEOUT = 5
SOCO_DISCOVER_TIMEOUT = 3
SONOS_STATE_CACHE_TTL_SECS = 30

_sonos_state_cache = None
_sonos_state_cache_time = 0

def ls_speakers():
    """Discover all Sonos speakers on the network."""
    speakers = {}
    discovered = soco.discover(timeout=SOCO_DISCOVER_TIMEOUT)
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
    for dev in list(soco.discover(timeout=SOCO_DISCOVER_TIMEOUT)):
        uri = dev.get_current_track_info()['uri']
        name = dev.player_name
        found[name] = uri
    return found

def _get_speaker_groups_zones(spk, speaker_name, ip_to_name):
    """Fetch groups and zones for a speaker.

    Returns (groups_list, zones_list). Runs with its own timeout so it doesn't
    block speaker data collection. Uses ip_to_name lookup to avoid network calls
    for player names.
    """
    speaker_groups = []
    speaker_zones = []
    try:
        for grp in spk.all_groups:
            if grp.coordinator is None:
                continue
            coord_ip = grp.coordinator.ip_address
            coord_name = ip_to_name.get(coord_ip)
            if coord_name is None:
                log.info("Speaker %s has coordinator %s, but this speaker doesn't exist.", speaker_name, coord_ip)
                continue
            members = []
            for m in grp.members:
                member_ip = m.ip_address
                member_name = ip_to_name.get(member_ip)
                if member_name is None:
                    log.info("Speaker %s says %s is in its group, but this speaker doesn't exist.", speaker_name, member_ip)
                    continue
                members.append(member_name)
            speaker_groups.append((coord_name, sorted(members)))
        for zone in spk.all_zones:
            zone_ip = zone.ip_address
            zone_name = ip_to_name.get(zone_ip)
            if zone_name is None:
                log.info("Speaker %s knows zone %s but no speaker is associated with it.", speaker_name, zone_ip)
                continue
            speaker_zones.append(zone_name)
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        log.warning("Failed to get groups or zones %s", speaker_name, exc_info=True)

    return speaker_groups, speaker_zones


def _get_single_speaker_state(spk):
    """Fetch basic state for a single speaker with timeout/exception handling.

    Returns (spk, speaker_data) or (spk, None) on failure.
    Operations that query the device (network calls) can timeout, so each is wrapped
    in exception handling.
    """
    speaker_data = {}
    speaker_data['ip_address'] = spk.ip_address

    # Get player name first - needed for logging and as the key
    try:
        speaker_data['name'] = spk.player_name
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        log.warning("Failed to get player name for speaker %s", speaker_data['ip_address'], exc_info=True)
        return spk, None

    log.info("Discovered '%s'", speaker_data['name'])

    # get_current_track_info() - queries device
    # Also derive is_playing_line_in/radio/tv from URI to avoid 3 extra network calls
    try:
        track_info = spk.get_current_track_info()
        uri = track_info.get('uri') or ''
        speaker_data['uri'] = uri
        speaker_data['is_playing_line_in'] = uri.startswith('x-rincon-stream:')
        speaker_data['is_playing_radio'] = uri.startswith((
            'x-sonosapi-stream:', 'x-sonosapi-radio:', 'x-rincon-mp3radio:', 'hls-radio:'
        ))
        speaker_data['is_playing_tv'] = uri.startswith('x-sonos-htastream:')
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        speaker_data['uri'] = None
        speaker_data['is_playing_line_in'] = None
        speaker_data['is_playing_radio'] = None
        speaker_data['is_playing_tv'] = None
        log.warning("Failed to get track info for %s", speaker_data['name'], exc_info=True)

    # get_current_transport_info() - queries device
    try:
        speaker_data['transport_state'] = spk.get_current_transport_info().get('current_transport_state')
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        speaker_data['transport_state'] = None
        log.warning("Failed to get transport info for %s", speaker_data['name'], exc_info=True)

    # get_current_media_info() - queries device
    try:
        speaker_data['current_media_info'] = spk.get_current_media_info()
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        speaker_data['current_media_info'] = {}
        log.warning("Failed to get media info for %s", speaker_data['name'], exc_info=True)

    # volume property - queries device
    try:
        speaker_data['volume'] = spk.volume
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        speaker_data['volume'] = None
        log.warning("Failed to get volume for %s", speaker_data['name'], exc_info=True)

    # is_coordinator property - queries device
    try:
        speaker_data['is_coordinator'] = spk.is_coordinator
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        speaker_data['is_coordinator'] = None
        log.warning("Failed to get coordinator status for %s", speaker_data['name'], exc_info=True)

    # get_speaker_info() - queries device
    try:
        speaker_data['speaker_info'] = spk.get_speaker_info()
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        speaker_data['speaker_info'] = {}
        log.warning("Failed to get speaker info for %s", speaker_data['name'], exc_info=True)

    return spk, speaker_data


def get_all_sonos_state(speaker_timeout_secs=10, groups_zones_timeout_secs=5):
    """Discover all Sonos speakers and return their state.

    Queries all speakers in parallel in two phases:
    1. Fetch basic speaker state (with speaker_timeout_secs timeout)
    2. Fetch groups/zones (with groups_zones_timeout_secs timeout)

    If groups/zones fetching fails or times out, speakers are still returned.
    Results are cached for SONOS_STATE_CACHE_TTL_SECS seconds.
    """
    global _sonos_state_cache, _sonos_state_cache_time

    # Return cached state if still valid
    if _sonos_state_cache is not None and (time.time() - _sonos_state_cache_time) < SONOS_STATE_CACHE_TTL_SECS:
        log.info("Returning cached Sonos state (age: %.1fs)", time.time() - _sonos_state_cache_time)
        return _sonos_state_cache

    speakers = []
    speakers_by_name = {}
    groups = {}
    zones = set()
    log.info("Discovering all Sonos speakers...")

    try:
        discovered = list(soco.discover(timeout=SOCO_DISCOVER_TIMEOUT) or [])
    except (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException):
        discovered = None
        log.warning("Failed to get Sonos network data, can't discover speakers", exc_info=True)

    if not discovered:
        return {
            'speakers': [],
            'groups': {},
            'zones': [],
        }

    with ThreadPoolExecutor(max_workers=len(discovered)) as executor:
        futures = {executor.submit(_get_single_speaker_state, spk): spk for spk in discovered}
        log.info("Discovering speakers details...")
        done, not_done = wait(futures, timeout=speaker_timeout_secs)
        log.info("Discovered %s speakers, %s failed", len(done), len(not_done))

        for future in not_done:
            future.cancel()
            spk = futures[future]
            log.warning("Timed out waiting for speaker state: %s", spk.ip_address)

        for future in done:
            try:
                spk, speaker_data = future.result()
                if speaker_data is None:
                    continue
                speakers.append(speaker_data)
                speakers_by_name[speaker_data['name']] = spk
            except Exception:
                log.warning("Exception getting speaker state", exc_info=True)

    if not speakers_by_name:
        return {
            'speakers': [],
            'groups': {},
            'zones': [],
        }

    log.info("Discovering Sonos zones and groups...")

    # Phase 2: Fetch groups/zones in parallel (this will query devices that are part of the group, so even if fetching
    # info for a speaker worked, fetching its coord/group status may fail)
    ip_to_name = {s['ip_address']: s['name'] for s in speakers}
    with ThreadPoolExecutor(max_workers=len(speakers_by_name)) as executor:
        futures = {
            executor.submit(_get_speaker_groups_zones, spk, name, ip_to_name): name
            for name, spk in speakers_by_name.items()
        }
        done, not_done = wait(futures, timeout=groups_zones_timeout_secs)

        for future in not_done:
            future.cancel()
            name = futures[future]
            log.warning("Timed out fetching groups/zones for %s", name)

        for future in done:
            try:
                speaker_groups, speaker_zones = future.result()
                for coord_name, members in speaker_groups:
                    groups[coord_name] = members
                for zone_name in speaker_zones:
                    zones.add(zone_name)
            except Exception:
                log.warning("Exception getting groups/zones", exc_info=True)

    _sonos_state_cache = {
        'speakers': sorted(speakers, key=lambda s: s['name']),
        'groups': dict(sorted(groups.items())),
        'zones': sorted(zones),
    }
    _sonos_state_cache_time = time.time()
    return _sonos_state_cache


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
