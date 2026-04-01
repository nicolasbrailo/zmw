import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


def _fake_model_dir(td, voice_ids):
    """Create fake .onnx files in a temp dir."""
    for vid in voice_ids:
        open(os.path.join(td, f"{vid}.onnx"), 'w').close()
        open(os.path.join(td, f"{vid}.onnx.json"), 'w').close()


class TestTts(unittest.TestCase):
    @patch('tts.PiperVoice')
    def test_auto_discovers_models(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium', 'es_ES-davefx-medium'])
            tts = Tts({'model_dir': td})
            self.assertEqual(len(tts._voices), 2)
            self.assertIn('en_US-lessac-medium', tts._voices)
            self.assertIn('es_ES-davefx-medium', tts._voices)

    @patch('tts.PiperVoice')
    def test_no_models_raises(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                Tts({'model_dir': td})

    @patch('tts.PiperVoice')
    def test_get_voices(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_GB-cori-medium', 'es_AR-daniela-high'])
            tts = Tts({'model_dir': td, 'default_language': 'en',
                        'defaults': {'es': 'es_AR-daniela-high'}})
            voices = tts.get_voices()
            self.assertEqual(len(voices), 2)
            by_id = {v['voice_id']: v for v in voices}
            # Cori is default for en (fallback language) and en_GB
            self.assertIn('default_for', by_id['en_GB-cori-medium'])
            self.assertTrue(by_id['en_GB-cori-medium']['default_fallback'])
            # Daniela is default for es
            self.assertIn('es', by_id['es_AR-daniela-high']['default_for'])
            self.assertNotIn('default_fallback', by_id['es_AR-daniela-high'])

    @patch('tts.PiperVoice')
    def test_resolve_exact_locale(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium', 'en_GB-cori-medium'])
            tts = Tts({'model_dir': td})
            vid, _ = tts.resolve_voice(language='en_GB')
            self.assertEqual(vid, 'en_GB-cori-medium')

    @patch('tts.PiperVoice')
    def test_resolve_lang_only_deterministic(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium', 'en_GB-cori-medium'])
            tts = Tts({'model_dir': td})
            vid1, _ = tts.resolve_voice(language='en')
            vid2, _ = tts.resolve_voice(language='en')
            self.assertEqual(vid1, vid2)

    @patch('tts.PiperVoice')
    def test_resolve_with_defaults_override(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium', 'en_GB-cori-medium'])
            tts = Tts({'model_dir': td, 'defaults': {'en': 'en_GB-cori-medium'}})
            vid, _ = tts.resolve_voice(language='en')
            self.assertEqual(vid, 'en_GB-cori-medium')

    @patch('tts.PiperVoice')
    def test_resolve_default_language(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium', 'es_ES-davefx-medium'])
            tts = Tts({'model_dir': td, 'default_language': 'es'})
            vid, _ = tts.resolve_voice()
            self.assertEqual(vid, 'es_ES-davefx-medium')

    @patch('tts.PiperVoice')
    def test_resolve_by_speaker(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium', 'en_GB-cori-medium'])
            tts = Tts({'model_dir': td})
            vid, _ = tts.resolve_voice(speaker='en_GB-cori-medium')
            self.assertEqual(vid, 'en_GB-cori-medium')

    @patch('tts.PiperVoice')
    def test_resolve_speaker_overrides_language(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium', 'es_ES-davefx-medium'])
            tts = Tts({'model_dir': td})
            vid, _ = tts.resolve_voice(language='en', speaker='es_ES-davefx-medium')
            self.assertEqual(vid, 'es_ES-davefx-medium')

    @patch('tts.PiperVoice')
    def test_resolve_unknown_lang_falls_back(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium'])
            tts = Tts({'model_dir': td, 'default_language': 'en'})
            vid, _ = tts.resolve_voice(language='zh')
            self.assertEqual(vid, 'en_US-lessac-medium')

    @patch('tts.subprocess.run')
    @patch('tts.os.remove')
    @patch('tts.wave.open')
    @patch('tts.PiperVoice')
    def test_synthesize_returns_mp3_and_voice_id(self, mock_piper, mock_wave, mock_rm, mock_sub):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium'])
            tts = Tts({'model_dir': td})
            mp3_path, voice_id = tts.synthesize("Hello")
            self.assertTrue(mp3_path.endswith(".mp3"))
            self.assertEqual(voice_id, 'en_US-lessac-medium')

    @patch('tts.PiperVoice')
    def test_defaults_invalid_voice_ignored(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_US-lessac-medium'])
            tts = Tts({'model_dir': td, 'defaults': {'en': 'nonexistent-voice'}})
            # Should fall back to auto-detected default
            vid, _ = tts.resolve_voice(language='en')
            self.assertEqual(vid, 'en_US-lessac-medium')


    @patch('tts.PiperVoice')
    def test_get_personality_configured(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_GB-alan-medium'])
            tts = Tts({'model_dir': td, 'speaker_configs': {
                'en_GB-alan-medium': {'personality': 'a grumpy butler'}
            }})
            self.assertEqual(tts.get_personality(speaker='en_GB-alan-medium'), 'a grumpy butler')

    @patch('tts.PiperVoice')
    def test_get_personality_not_configured(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_GB-alan-medium'])
            tts = Tts({'model_dir': td})
            self.assertIsNone(tts.get_personality(speaker='en_GB-alan-medium'))

    @patch('tts.PiperVoice')
    def test_get_personality_resolves_language(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_GB-alan-medium'])
            tts = Tts({'model_dir': td, 'default_language': 'en',
                        'speaker_configs': {
                            'en_GB-alan-medium': {'personality': 'a grumpy butler'}
                        }})
            self.assertEqual(tts.get_personality(language='en'), 'a grumpy butler')

    @patch('tts.PiperVoice')
    def test_get_voices_includes_personality(self, mock_piper):
        from tts import Tts
        with tempfile.TemporaryDirectory() as td:
            _fake_model_dir(td, ['en_GB-alan-medium', 'en_US-lessac-medium'])
            tts = Tts({'model_dir': td, 'speaker_configs': {
                'en_GB-alan-medium': {'personality': 'a grumpy butler'}
            }})
            voices = tts.get_voices()
            by_id = {v['voice_id']: v for v in voices}
            self.assertEqual(by_id['en_GB-alan-medium']['personality'], 'a grumpy butler')
            self.assertNotIn('personality', by_id['en_US-lessac-medium'])


if __name__ == '__main__':
    unittest.main()
