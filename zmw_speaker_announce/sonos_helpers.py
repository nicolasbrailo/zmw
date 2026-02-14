"""Helper functions for Sonos speaker discovery and configuration."""
import logging
import requests
import soco
from soco import discover

from zzmw_lib.logs import build_logger

log = build_logger("SpeakerAnnounceSonosHelpers")

# Set timeout for all SoCo HTTP requests to speakers (default is None/no timeout)
soco.config.REQUEST_TIMEOUT = 5
SOCO_DISCOVER_TIMEOUT = 3

_SONOS_EXC = (requests.exceptions.Timeout, requests.exceptions.RequestException, soco.exceptions.SoCoException)

def config_soco_logger(use_debug_log):
    """Configure logging level for soco library."""
    if not use_debug_log:
        logging.getLogger('soco.*').setLevel(logging.INFO)
        logging.getLogger('soco.core').setLevel(logging.INFO)
        logging.getLogger('soco.services').setLevel(logging.INFO)
        logging.getLogger('soco.discovery').setLevel(logging.INFO)
        logging.getLogger('soco.zonegroupstate').setLevel(logging.INFO)
        logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)


def get_sonos_by_name():
    """ Returns a map of all LAN Sonos players """
    all_sonos = {}
    try:
        discovered = discover(timeout=SOCO_DISCOVER_TIMEOUT)
    except _SONOS_EXC:
        log.warning("Failed to discover Sonos speakers", exc_info=True)
        return all_sonos

    if not discovered:
        return all_sonos

    for player_obj in discovered:
        try:
            all_sonos[player_obj.player_name] = player_obj
        except _SONOS_EXC:
            log.warning("Failed to get name for speaker %s, skipping", player_obj.ip_address, exc_info=True)
    return all_sonos
