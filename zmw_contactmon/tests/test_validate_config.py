"""Unit tests for validate_config.py"""
import os
import tempfile
import pytest
from validate_config import validate_cfg_actions


class TestValidateCfgActions:
    """Test validate_cfg_actions function"""

    def setup_method(self):
        """Create temporary directories for test assets"""
        self.temp_dir = tempfile.mkdtemp()
        self.www_dir = os.path.join(self.temp_dir, 'www')
        os.makedirs(self.www_dir)
        # Create a test sound file
        self.test_sound = os.path.join(self.www_dir, 'test.mp3')
        with open(self.test_sound, 'w') as f:
            f.write('test')
        self.www_public_url = 'http://example.com'

    def test_valid_config(self):
        """Test valid configuration passes"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'timeout_secs': 300,
                    'open': {
                        'telegram': {'msg': 'Door opened'}
                    }
                }
            }
        }
        result = validate_cfg_actions(self.www_dir, self.www_public_url, cfg)
        assert result == cfg['actions']

    def test_invalid_event_type(self):
        """Test invalid event type raises KeyError"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'invalid_event': {}
                }
            }
        }
        with pytest.raises(KeyError, match="Invalid actions.*only"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_missing_normal_state(self):
        """Test missing normal_state raises ValueError"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'timeout_secs': 300
                }
            }
        }
        with pytest.raises(ValueError, match="missing normal_state"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_normal_state_not_boolean(self):
        """Test normal_state must be boolean"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': 'true',
                    'open': {}
                }
            }
        }
        with pytest.raises(ValueError, match="normal state must be a boolean"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_timeout_secs_not_int(self):
        """Test timeout_secs must be int"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'timeout_secs': '300'
                }
            }
        }
        with pytest.raises(ValueError, match="timeout must be an int"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_timeout_secs_too_small(self):
        """Test timeout_secs must be > 5"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'timeout_secs': 3
                }
            }
        }
        with pytest.raises(ValueError, match="must be between 5 seconds"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_timeout_secs_too_large(self):
        """Test timeout_secs must be < 1 day"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'timeout_secs': 90000
                }
            }
        }
        with pytest.raises(ValueError, match="must be between 5 seconds"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_timeout_event_without_timeout_secs(self):
        """Test timeout event requires timeout_secs"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'timeout': {
                        'telegram': {'msg': 'Timeout'}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="defined timeout action, but no timeout specified"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_curfew_event_without_curfew_hour(self):
        """Test curfew event requires curfew_hour in config"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'curfew': {
                        'telegram': {'msg': 'Curfew alert'}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="defined curfew action, but no curfew specified"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_invalid_action_type(self):
        """Test invalid action type raises KeyError"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'invalid_action': {'msg': 'test'}
                    }
                }
            }
        }
        with pytest.raises(KeyError, match="Invalid actions.*Known actions"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_telegram_missing_msg(self):
        """Test telegram action requires msg"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'telegram': {}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="Telegram notification but is missing a message"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_whatsapp_missing_msg(self):
        """Test whatsapp action requires msg"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'whatsapp': {}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="Whatsapp notification but is missing a message"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_tts_and_sound_asset_both_present(self):
        """Test tts_announce and sound_asset_announce cannot both be present"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'tts_announce': {'lang': 'en', 'msg': 'Test'},
                        'sound_asset_announce': {'public_www': '/test.mp3'}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="announce a TTS message and a local sound asset"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_tts_announce_missing_msg(self):
        """Test tts_announce requires msg"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'tts_announce': {'lang': 'en'}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="TTS announce but is missing a message"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_sound_asset_announce_missing_path(self):
        """Test sound_asset_announce requires public_www"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'sound_asset_announce': {}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="doesn't specify what to announce"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_sound_asset_local_path_not_supported(self):
        """Test sound_asset_announce rejects local_path (no longer supported by ZmwSpeakerAnnounce)"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'sound_asset_announce': {'local_path': self.test_sound}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="doesn't specify what to announce"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_sound_asset_public_www_not_exist(self):
        """Test sound_asset_announce public_www (relative) must exist"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'sound_asset_announce': {'public_www': '/nonexistent.mp3'}
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="non existent file"):
            validate_cfg_actions(self.www_dir, self.www_public_url, cfg)

    def test_sound_asset_public_www_valid(self):
        """Test sound_asset_announce with valid public_www converts to full URL"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'sound_asset_announce': {'public_www': '/test.mp3'}
                    }
                }
            }
        }
        result = validate_cfg_actions(self.www_dir, self.www_public_url, cfg)
        assert result['SensorName1']['open']['sound_asset_announce']['public_www'] == 'http://example.com/test.mp3'

    def test_sound_asset_external_url(self):
        """Test sound_asset_announce with external URL (no leading slash)"""
        cfg = {
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'open': {
                        'sound_asset_announce': {'public_www': 'http://external.com/sound.mp3'}
                    }
                }
            }
        }
        result = validate_cfg_actions(self.www_dir, self.www_public_url, cfg)
        assert result['SensorName1']['open']['sound_asset_announce']['public_www'] == 'http://external.com/sound.mp3'

    def test_curfew_with_curfew_hour(self):
        """Test curfew event with curfew_hour in config passes"""
        cfg = {
            'curfew_hour': '22:00',
            'actions': {
                'SensorName1': {
                    'normal_state': True,
                    'curfew': {
                        'telegram': {'msg': 'Curfew alert'}
                    }
                }
            }
        }
        result = validate_cfg_actions(self.www_dir, self.www_public_url, cfg)
        assert 'SensorName1' in result
