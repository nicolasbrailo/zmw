""" Checks if cfg file is valid """
import os

def validate_cfg_actions(www_local_path, www_public_url, cfg):
    """
    Validate sensor action configurations.

    Validates that all sensor actions are properly configured with correct
    event types, action types, and required parameters.

    Args:
        www_local_path: Local filesystem path to www directory
        www_public_url: Public URL base for www resources
        all_actions: Dictionary of sensor_name -> events -> actions configuration

    Raises:
        KeyError: If invalid action or event types are specified
        ValueError: If required configuration is missing or invalid
    """
    valid_acts = set(['telegram', 'whatsapp', 'tts_announce', 'sound_asset_announce'])
    valid_events = set(['normal_state', 'timeout_secs', 'open', 'close', 'timeout', 'curfew'])
    all_actions = cfg['actions']

    for sensor,acts in all_actions.items():
        if not set(acts.keys()).issubset(valid_events):
            raise KeyError(f"Invalid actions '{acts.keys()}' for sensor {sensor}, only {valid_events} are valid")
        if 'normal_state' not in acts:
            raise ValueError(f"{sensor} missing normal_state configuration")

        for evt,act_descr in acts.items():
            if evt == 'normal_state':
                if not isinstance(act_descr, bool):
                    raise ValueError(f"Sensor {sensor}: normal state must be a boolean")
                continue

            if evt == 'timeout_secs':
                if not isinstance(act_descr, int):
                    raise ValueError(f"Sensor {sensor}: normal state timeout must be an int, not {act_descr}")
                if not(5 < act_descr < 60 * 60 * 24):
                    raise ValueError(f"Sensor {sensor}: normal state timeout must be between 5 seconds and 1 day")
                continue

            if evt == 'timeout' and 'timeout_secs' not in acts:
                raise ValueError(f"Sensor {sensor}: defined timeout action, but no timeout specified")

            if evt == 'curfew' and 'curfew_hour' not in cfg:
                raise ValueError(f"Sensor {sensor}: defined curfew action, but no curfew specified")

            for act in act_descr:
                if act not in valid_acts:
                    raise KeyError(f"Invalid actions '{act}' for sensor {sensor}.{evt}. Known actions: {valid_acts}")

            if 'telegram' in act_descr and 'msg' not in act_descr['telegram']:
                raise ValueError(f"Sensor {sensor}.{evt} requests Telegram notification but is missing a message")
            if 'whatsapp' in act_descr and 'msg' not in act_descr['whatsapp']:
                raise ValueError(f"Sensor {sensor}.{evt} requests Whatsapp notification but is missing a message")
            if 'tts_announce' in act_descr:
                if 'sound_asset_announce' in act_descr:
                    raise ValueError(
                        f"Sensor {sensor}.{evt} will try to announce a TTS message "
                        "and a local sound asset. This is unlikely to work."
                    )
                if 'msg' not in act_descr['tts_announce']:
                    raise ValueError(f"Sensor {sensor}.{evt} requests TTS announce but is missing a message")
            if 'sound_asset_announce' in act_descr:
                if 'tts_announce' in act_descr:
                    raise ValueError(
                        f"Sensor {sensor}.{evt} will try to announce a TTS message "
                        "and a local sound asset. This is unlikely to work."
                    )
                if 'public_www' not in act_descr['sound_asset_announce']:
                    raise ValueError(
                        f"Sensor {sensor}.{evt} requests announcement "
                        "but doesn't specify what to announce (public_www)"
                    )
                if ('public_www' in act_descr['sound_asset_announce'] and
                        act_descr['sound_asset_announce']['public_www'][0] == '/'):
                    # If fn starts with `/`, assume it's relative to local path
                    # (ie of this www server), else it's a full URL
                    fp = os.path.join(
                        www_local_path,
                        '.' + act_descr['sound_asset_announce']['public_www']
                    )
                    if not os.path.isfile(fp):
                        raise ValueError(
                            f"Sensor {sensor}.{evt} will request announcement of "
                            f"non existent file {www_local_path}{fp}"
                        )
                    # Convert to public full URL
                    act_descr['sound_asset_announce']['public_www'] = (
                        www_public_url + act_descr['sound_asset_announce']['public_www']
                    )
    return all_actions
