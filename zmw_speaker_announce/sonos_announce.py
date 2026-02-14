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

async def _sonos_ws_connect(api_key, ip_addr):
    uri = f"wss://{ip_addr}:1443/websocket/api"
    headers = {
        "X-Sonos-Api-Key": api_key,
        "Sec-WebSocket-Protocol": "v1.api.smartspeaker.audio",
    }
    log.debug("Opening websocket to %s", uri)
    session = aiohttp.ClientSession()
    try:
        session.ws = await session.ws_connect(uri, headers=headers, verify_ssl=False)
    except aiohttp.ClientResponseError as exc:
        log.error("HTTP error %s connecting to Sonos@'%s'", exc.code, uri)
    except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
        log.error("Network error connecting to Sonos@'%s'", uri)
    except aiohttp.ClientError:
        log.error("Unknown error connecting to Sonos speaker %s", uri, exc_info=True)
    except Exception:
        log.error("Unknown wild exception connecting to Sonos speaker %s", uri, exc_info=True)
    else:
        return session
    try:
        await session.close()
    except Exception:
        pass
    return None


async def _async_sonos_announce_one(api_cfg, ip_addr, soco_uid, alert_uri, volume=None):
    # ~Inspired on~ stolen from
    # https://github.com/jjlawren/sonos-websocket/blob/main/sonos_websocket/websocket.py
    session = await _sonos_ws_connect(api_cfg['api_key'], ip_addr)
    if session is None or session.ws is None:
        return

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
        await session.ws.receive()
        #log.debug("Speaker %s replies %s", ip_addr, str(msg))
    except (aiohttp.ClientError, TypeError, ValueError):
        log.error("Error sending command to Sonos@'%s'", ip_addr, exc_info=True)

    try:
        await session.ws.close()
        await session.close()
    except (aiohttp.ClientError, OSError):
        log.error("Error closing connection to Sonos@'%s'", ip_addr, exc_info=True)
    return True


async def _async_sonos_announce_all(api_cfg, alert_uri, volume=None):
    tasks = []

    if 'speaker_ip_list' in api_cfg:
        log.info("Skip Sonos discovery, using static IP list %s", api_cfg['speaker_ip_list'])
        for ip in api_cfg['speaker_ip_list']:
            try:
                dev = soco.SoCo(ip)
                tasks.append(_async_sonos_announce_one(api_cfg, dev.ip_address, dev.uid, alert_uri, volume))
            except _SONOS_EXC:
                log.warning("Failed to connect to speaker at %s, skipping", ip, exc_info=True)
    else:
        try:
            spks = soco.discover(timeout=SOCO_DISCOVER_TIMEOUT)
        except _SONOS_EXC:
            log.error("Sonos discovery failed", exc_info=True)
            return False
        if spks is None:
            log.error("Sonos discovery broken, can't announce")
            return False
        for spk in spks:
            tasks.append(_async_sonos_announce_one(api_cfg, spk.ip_address, spk.uid, alert_uri, volume))

    if not tasks:
        log.error("No speakers available for announcement")
        return False

    await asyncio.gather(*tasks)
    return True


def sonos_announce_ws(api_cfg, alert_uri, volume=None):
    """ Send an announcement to all zones, in a fancy way: should lower the volume of current media,
    play announce and then restore. Requires an API key """
    # Ensure we have the right cfg keys before launching an announcement
    api_cfg['api_key']  # pylint: disable=pointless-statement
    api_cfg['api_key_name']  # pylint: disable=pointless-statement
    api_cfg['key_app_id']  # pylint: disable=pointless-statement
    return asyncio.run(_async_sonos_announce_all(api_cfg, alert_uri, volume))

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
    sonos_announce_ws """
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


def sonos_announce(alert_uri, volume=None, ws_api_cfg=None):
    """ Make an announcement over all discoverable speakers. If ws_api_cfg isn't false, it will
    use a 'smart' announce method (lower volume of current media, announce, restore). This requires
    an external API key. If this method isn't available, it will fallback to announce only on
    speakers without active media. """
    if ws_api_cfg is not None:
        try:
            if sonos_announce_ws(ws_api_cfg, alert_uri, volume):
                return
        except (KeyError, aiohttp.ClientError, OSError, asyncio.TimeoutError):
            log.error('Failed to Sonos announce', exc_info=True)

    log.error('Smart Sonos announce failed, fallback to local announce')
    sonos_announce_local(alert_uri, volume, timeout=10, force_play=False)
