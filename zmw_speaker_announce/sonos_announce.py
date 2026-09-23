"""
Random Sonos helpers.

Alarm/announcement system inspired from
https://github.com/SoCo/SoCo/blob/master/examples/snapshot/multi_zone_snap.py
https://github.com/jishi/node-sonos-http-api/blob/master/lib/helpers/all-player-announcement.js
https://github.com/jjlawren/sonos-websocket/tree/main
"""

import aiohttp
import asyncio
import requests
import soco
import time

from soco.snapshot import Snapshot
from zzmw_lib.logs import build_logger
from sonos_helpers import SOCO_DISCOVER_TIMEOUT

log = build_logger("MqttSpeakerAnnounceSonos")

_SONOS_EXC = (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException)

# In synced mode all websockets are opened before any announcement is sent, so a slow speaker delays
# everyone. Cap how long we'll wait for one to connect; speakers that don't make it are skipped.
_SONOS_WS_CONNECT_TIMEOUT_SECS = 3
# Max time to wait for a speaker to ack a loadAudioClip command, before giving up and closing the socket
_SONOS_WS_REPLY_TIMEOUT_SECS = 5

async def _sonos_ws_connect(api_key, ip_addr):
    uri = f"wss://{ip_addr}:1443/websocket/api"
    headers = {
        "X-Sonos-Api-Key": api_key,
        "Sec-WebSocket-Protocol": "v1.api.smartspeaker.audio",
    }
    log.debug("Opening websocket to %s", uri)
    session = aiohttp.ClientSession()
    t0 = time.monotonic()
    try:
        session.ws = await asyncio.wait_for(session.ws_connect(uri, headers=headers, verify_ssl=False),
                                            timeout=_SONOS_WS_CONNECT_TIMEOUT_SECS)
    except aiohttp.ClientResponseError as exc:
        log.error("HTTP error %s connecting to Sonos@'%s'", exc.code, uri)
    except asyncio.TimeoutError:
        log.error("Timeout after %.2fs connecting to Sonos@'%s'", time.monotonic() - t0, uri)
    except aiohttp.ClientConnectionError:
        log.error("Network error after %.2fs connecting to Sonos@'%s'", time.monotonic() - t0, uri)
    except aiohttp.ClientError:
        log.error("Unknown error connecting to Sonos speaker %s", uri, exc_info=True)
    except Exception:
        log.error("Unknown wild exception connecting to Sonos speaker %s", uri, exc_info=True)
    else:
        log.info("Connected to Sonos@%s in %.2fs", ip_addr, time.monotonic() - t0)
        return session
    try:
        await session.close()
    except Exception:
        pass
    return None


async def _async_sonos_send_clip(session, ip_addr, soco_uid, api_cfg, alert_uri, volume=None):
    """ Returns True if the command was sent """
    # ~Inspired on~ stolen from
    # https://github.com/jjlawren/sonos-websocket/blob/main/sonos_websocket/websocket.py
    command = {
        "namespace": "audioClip:1",
        "command": "loadAudioClip",
        "playerId": soco_uid,
    }
    options = {
        "name": api_cfg['api_key_name'],
        "appId": api_cfg['key_app_id'],
        "streamUrl": alert_uri,
    }

    if volume is not None:
        options["volume"] = volume

    try:
        await session.ws.send_json([command, options])
        log.info("Asked speaker %s to play %s", ip_addr, alert_uri)
        return True
    except (aiohttp.ClientError, TypeError, ValueError):
        log.error("Error sending command to Sonos@'%s'", ip_addr, exc_info=True)
        return False


async def _async_sonos_close(session, ip_addr):
    try:
        await session.ws.close()
        await session.close()
    except (aiohttp.ClientError, OSError):
        log.error("Error closing connection to Sonos@'%s'", ip_addr, exc_info=True)


async def _async_sonos_wait_and_close(session, ip_addr, clip_sent):
    # If the command wasn't sent there's no reply to wait for, just clean up
    if clip_sent:
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(session.ws.receive(), timeout=_SONOS_WS_REPLY_TIMEOUT_SECS)
            log.info("Sonos@%s replied in %.2fs", ip_addr, time.monotonic() - t0)
        except asyncio.TimeoutError:
            log.warning("Timeout after %ss waiting for reply from Sonos@'%s'",
                        _SONOS_WS_REPLY_TIMEOUT_SECS, ip_addr)
        except (aiohttp.ClientError, TypeError, ValueError):
            log.warning("Error reading reply from Sonos@'%s'", ip_addr, exc_info=True)

    await _async_sonos_close(session, ip_addr)


async def _async_sonos_announce_one(api_cfg, ip_addr, soco_uid, alert_uri, volume=None):
    """ Connect, send and close a single speaker. Returns True if the clip was sent. """
    session = await _sonos_ws_connect(api_cfg['api_key'], ip_addr)
    if session is None:
        return False
    sent = await _async_sonos_send_clip(session, ip_addr, soco_uid, api_cfg, alert_uri, volume)
    await _async_sonos_wait_and_close(session, ip_addr, sent)
    return sent


def _log_announce_summary(ips, sent):
    failed = [ip for ip, was_sent in zip(ips, sent) if not was_sent]
    log.info("Announcement sent to %d/%d speakers", len(ips) - len(failed), len(ips))
    if failed:
        log.warning("Speakers that didn't get the announcement: %s", failed)


async def _async_sonos_announce_many_fast(api_cfg, targets, alert_uri, volume=None):
    """ Announce on a list of (ip_addr, soco_uid) targets. Each speaker is asked to play as soon as its
    connection is up, so playback may be skewed by the difference in connection setup time between
    speakers. Returns True if at least one speaker was asked to play. """
    sent = await asyncio.gather(*[_async_sonos_announce_one(api_cfg, ip, uid, alert_uri, volume)
                                  for ip, uid in targets])
    _log_announce_summary([ip for ip, _ in targets], sent)
    if not any(sent):
        log.error("Couldn't send announcement to any speaker")
        return False
    return True


async def _async_sonos_announce_many_synced(api_cfg, targets, alert_uri, volume=None):
    """ Announce on a list of (ip_addr, soco_uid) targets. Connections are all established before any
    command is sent, so that connection setup time (TLS handshake, which varies per speaker) doesn't
    translate into playback skew between speakers. Returns True if at least one speaker was asked to
    play. """
    sessions = await asyncio.gather(*[_sonos_ws_connect(api_cfg['api_key'], ip) for ip, _ in targets])
    connected = [(sess, ip, uid) for sess, (ip, uid) in zip(sessions, targets) if sess is not None]
    if not connected:
        log.error("Couldn't connect to any speaker for announcement")
        return False

    sent = await asyncio.gather(*[_async_sonos_send_clip(sess, ip, uid, api_cfg, alert_uri, volume)
                                  for sess, ip, uid in connected])
    await asyncio.gather(*[_async_sonos_wait_and_close(sess, ip, was_sent)
                           for (sess, ip, _), was_sent in zip(connected, sent)])
    sent_ips = {ip for (_, ip, _), was_sent in zip(connected, sent) if was_sent}
    _log_announce_summary([ip for ip, _ in targets], [ip in sent_ips for ip, _ in targets])
    if not any(sent):
        log.error("Couldn't send announcement to any speaker")
        return False
    return True


def _get_speaker_name(spk):
    """ Returns the speaker name, or None if it can't be retrieved. This is a blocking network call per
    speaker, which takes REQUEST_TIMEOUT if the speaker is dead. """
    t0 = time.monotonic()
    try:
        return spk.player_name
    except _SONOS_EXC:
        log.warning("Failed to get name for speaker %s after %.2fs, skipping",
                    spk.ip_address, time.monotonic() - t0, exc_info=True)
        return None


def _get_announce_targets(api_cfg, speakers):
    """ Returns a list of (ip_addr, soco_uid) to announce on, or None if discovery failed. Speaker
    names are only looked up if speakers is set: it's slow, and blocks on dead speakers. """
    t0 = time.monotonic()
    if 'speaker_ip_list' in api_cfg:
        log.info("Skip Sonos discovery, using static IP list %s", api_cfg['speaker_ip_list'])
        spks = []
        for ip in api_cfg['speaker_ip_list']:
            try:
                dev = soco.SoCo(ip)
                # Force the uid lookup here, so a dead speaker is caught by this try block
                dev.uid  # pylint: disable=pointless-statement
                spks.append(dev)
            except _SONOS_EXC:
                log.warning("Failed to connect to speaker at %s after %.2fs, skipping",
                            ip, time.monotonic() - t0, exc_info=True)
    else:
        try:
            spks = soco.discover(timeout=SOCO_DISCOVER_TIMEOUT)
        except _SONOS_EXC:
            log.error("Sonos discovery failed", exc_info=True)
            return None
        if spks is None:
            log.error("Sonos discovery broken, can't announce")
            return None
    log.info("Found %d Sonos speakers in %.2fs: %s", len(spks), time.monotonic() - t0,
             sorted(spk.ip_address for spk in spks))

    if not speakers:
        return [(spk.ip_address, spk.uid) for spk in spks]

    t0 = time.monotonic()
    targets = []
    announced_names = []
    for spk in spks:
        name = _get_speaker_name(spk)
        if name is None:
            continue
        if name not in speakers:
            log.debug("Skipping speaker %s (not in requested list)", name)
            continue
        announced_names.append(name)
        targets.append((spk.ip_address, spk.uid))
    log.info("Resolved speaker names in %.2fs", time.monotonic() - t0)

    missing = set(speakers) - set(announced_names)
    if missing:
        log.error("Requested speakers not found: %s", sorted(missing))
    return targets


async def _async_sonos_announce_all(api_cfg, alert_uri, volume=None, speakers=None, *, synced):
    targets = _get_announce_targets(api_cfg, speakers)
    if not targets:
        log.error("No speakers available for announcement")
        return False

    log.info("Announcing %s on %d speakers (%s)", alert_uri, len(targets), "synced" if synced else "fast")
    t0 = time.monotonic()
    if synced:
        ok = await _async_sonos_announce_many_synced(api_cfg, targets, alert_uri, volume)
    else:
        ok = await _async_sonos_announce_many_fast(api_cfg, targets, alert_uri, volume)
    log.info("Announcement done in %.2fs", time.monotonic() - t0)
    return ok


def sonos_announce_ws(api_cfg, alert_uri, volume=None, speakers=None, *, synced):
    """ Send an announcement to all zones, in a fancy way: should lower the volume of current media,
    play announce and then restore. Requires an API key. If synced, try harder to start playback at
    the same time on all speakers (slower). Returns False if no speaker could be asked to play. """
    # Ensure we have the right cfg keys before launching an announcement
    api_cfg['api_key']  # pylint: disable=pointless-statement
    api_cfg['api_key_name']  # pylint: disable=pointless-statement
    api_cfg['key_app_id']  # pylint: disable=pointless-statement
    return asyncio.run(_async_sonos_announce_all(api_cfg, alert_uri, volume, speakers=speakers, synced=synced))

def _sonos_announce_local_prep_zones(volume, force_play):
    try:
        zones = soco.discover(timeout=SOCO_DISCOVER_TIMEOUT)
    except _SONOS_EXC:
        log.error("Sonos discovery failed", exc_info=True)
        return []

    if zones is None:
        log.error("Sonos discovery is broken, can't find zones")
        return []

    announce_zones = []
    for zone in zones:
        try:
            zone_name = zone.player_name
        except _SONOS_EXC:
            log.warning("Failed to get name for zone %s, skipping", zone.ip_address, exc_info=True)
            continue

        try:
            trans_state = zone.get_current_transport_info()
            is_playing = trans_state["current_transport_state"] == "PLAYING"
        except _SONOS_EXC:
            log.warning("Failed to get transport info for %s, skipping", zone_name, exc_info=True)
            continue

        try:
            playing_tv = zone.is_playing_tv
        except _SONOS_EXC:
            log.warning("Failed to check TV state for %s, assuming not playing TV", zone_name, exc_info=True)
            playing_tv = False

        non_pausable_play = is_playing and not force_play
        non_pausable_media = non_pausable_play or playing_tv
        if non_pausable_media:
            log.info('Will skip %s from announcement, currently playing media', zone_name)
            continue

        try:
            is_coord = zone.is_coordinator
        except _SONOS_EXC:
            log.warning("Failed to check coordinator status for %s, assuming not coordinator", zone_name, exc_info=True)
            is_coord = False

        # Each Sonos group has one coordinator only these can play, pause, etc.
        if is_coord and is_playing:
            try:
                zone.pause()
            except _SONOS_EXC:
                log.warning("Failed to pause %s", zone_name, exc_info=True)

        # For every Sonos player set volume and mute for every zone, then save state
        try:
            zone.mute = False
            zone.volume = volume or 50
        except _SONOS_EXC:
            log.warning("Failed to set volume/mute for %s, skipping", zone_name, exc_info=True)
            continue

        try:
            zone.snap = Snapshot(zone)
            zone.snap.snapshot()
        except _SONOS_EXC:
            log.warning("Failed to snapshot %s, skipping", zone_name, exc_info=True)
            continue

        announce_zones.append(zone)
    return announce_zones

def sonos_announce_local(alert_uri, volume, timeout, force_play):
    """ Send an announcement to all zones, using local only APIs. Use as a fallback for
    sonos_announce_ws. Speaker filtering is not supported here to keep the fallback simple. """
    log.info('Preparing announcement %s volume %s timeout %s', alert_uri, volume, timeout)
    announce_zones = _sonos_announce_local_prep_zones(volume, force_play)
    if len(announce_zones) == 0:
        log.warning("Can't find speakers to announce")
        return

    # play the sound (uri) on each sonos coordinator
    log.info('Requesting Sonos to play announcement: %s', alert_uri)
    for zone in announce_zones:
        log.info('  ask %s to play announcement', zone.player_name)
        if zone.is_coordinator:
            try:
                zone.play_uri(uri=alert_uri, title="Sonos Alert")
            except (soco.exceptions.SoCoException, OSError):
                log.error('Failed to announce on %s', zone.player_name, exc_info=True)

    # Sleep to synchronize: make sure we're not checking for announcement finished
    # before the speaker had time to process the announce request
    time.sleep(1)

    # Wait for alert to finish (or timeout)
    announcement_finished = False
    finished_waits = 0
    while not announcement_finished:
        log.info('Waiting for announcement to finish...')
        for zone in announce_zones:
            # transport info isn't reliable for all device types (eg Sonos amps may say they are
            # always playing when line-in is connected), so we wait until any single device says
            # that playback is fininshed: if announcement was sent to all devices, any of them
            # finishing should be an indication that the real announcement is
            # finished.
            try:
                trans_state = zone.get_current_transport_info()
                if trans_state["current_transport_state"] != "PLAYING":
                    announcement_finished = True
                    break
            except _SONOS_EXC:
                log.warning("Failed to check transport state for %s during wait", zone.player_name, exc_info=True)

        if not announcement_finished:
            time.sleep(1)
            finished_waits += 1
            if finished_waits >= timeout:
                log.error('Announcement still playing after timeout of %s seconds, will force stop', timeout)
                break

    # restore each zone to previous state
    for zone in announce_zones:
        log.info('Restoring state for %s', zone.player_name)
        try:
            zone.snap.restore(fade=True)
        except (soco.exceptions.SoCoException, OSError):
            log.error('Failed to restore state on %s', zone.player_name, exc_info=True)


def sonos_announce(alert_uri, volume=None, ws_api_cfg=None, speakers=None, *, synced):
    """ Make an announcement over all discoverable speakers. If ws_api_cfg isn't false, it will
    use a 'smart' announce method (lower volume of current media, announce, restore). This requires
    an external API key. If this method isn't available, it will fallback to announce only on
    speakers without active media (and speaker selection won't be applied). If synced, the smart
    announce method will try harder to start playback at the same time on all speakers; use it for
    announcements where a skew is noticeable (eg TTS). """
    if ws_api_cfg is not None:
        try:
            if sonos_announce_ws(ws_api_cfg, alert_uri, volume, speakers=speakers, synced=synced):
                return
        except (KeyError, aiohttp.ClientError, OSError, asyncio.TimeoutError):
            log.error('Failed to Sonos announce', exc_info=True)

    # Fallback to local announce — speaker filtering not supported to keep fallback simple
    log.error('Smart Sonos announce failed, fallback to local announce')
    sonos_announce_local(alert_uri, volume, timeout=10, force_play=False)
