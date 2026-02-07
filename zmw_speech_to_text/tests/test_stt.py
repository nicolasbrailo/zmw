import unittest
from unittest.mock import patch, MagicMock


class FakeSegment:
    def __init__(self, text, avg_logprob=-0.3, no_speech_prob=0.01):
        self.text = text
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


def fake_info(language='en', language_probability=0.95):
    info = MagicMock()
    info.language = language
    info.language_probability = language_probability
    return info


class TestStt(unittest.TestCase):
    @patch('stt.WhisperModel')
    def test_construct_default_config(self, mock_model_cls):
        from stt import Stt
        stt = Stt({'local_files_only': True})
        mock_model_cls.assert_called_once_with('tiny.en', compute_type='int8',
                                               download_root='./stt_model',
                                               local_files_only=True)

    @patch('stt.WhisperModel')
    def test_construct_custom_config(self, mock_model_cls):
        from stt import Stt
        stt = Stt({'model_size': 'base.en', 'compute_type': 'float16',
                    'language': 'es', 'beam_size': 3, 'local_files_only': False})
        mock_model_cls.assert_called_once_with('base.en', compute_type='float16',
                                               download_root='./stt_model',
                                               local_files_only=False)
        self.assertEqual(stt._language, 'es')
        self.assertEqual(stt._beam_size, 3)

    def test_construct_missing_local_files_only_raises(self):
        from stt import Stt
        with self.assertRaises(KeyError):
            Stt({})

    @patch('stt.os.path.isfile', return_value=True)
    @patch('stt.WhisperModel')
    def test_transcribe_file(self, mock_model_cls, _mock_isfile):
        from stt import Stt
        mock_model = mock_model_cls.return_value
        mock_model.transcribe.return_value = (
            iter([FakeSegment(" hello ", -0.25, 0.02), FakeSegment(" world ", -0.35, 0.01)]),
            fake_info('en', 0.98),
        )
        stt = Stt({'local_files_only': True})
        text, confidence = stt.transcribe_file('/tmp/test.wav')
        self.assertEqual(text, 'hello world')
        self.assertEqual(confidence['language'], 'en')
        self.assertEqual(confidence['language_prob'], 0.98)
        self.assertAlmostEqual(confidence['avg_log_prob'], -0.3, places=3)
        self.assertAlmostEqual(confidence['no_speech_prob'], 0.015, places=3)
        mock_model.transcribe.assert_called_once()
        args, kwargs = mock_model.transcribe.call_args
        self.assertEqual(args[0], '/tmp/test.wav')
        self.assertEqual(kwargs['language'], 'en')
        self.assertEqual(kwargs['beam_size'], 5)

    @patch('stt.os.path.isfile', return_value=False)
    @patch('stt.WhisperModel')
    def test_transcribe_file_not_found(self, mock_model_cls, _mock_isfile):
        from stt import Stt
        stt = Stt({'local_files_only': True})
        result = stt.transcribe_file('/tmp/nonexistent.wav')
        self.assertIsNone(result)
        mock_model_cls.return_value.transcribe.assert_not_called()

    @patch('stt.WhisperModel')
    def test_transcribe_bytes(self, mock_model_cls):
        from stt import Stt
        mock_model = mock_model_cls.return_value
        mock_model.transcribe.return_value = (
            iter([FakeSegment("test transcription")]),
            fake_info(),
        )
        stt = Stt({'local_files_only': True})
        text, confidence = stt.transcribe_bytes(b'\x00\x01\x02\x03')
        self.assertEqual(text, 'test transcription')
        self.assertIn('language', confidence)
        mock_model.transcribe.assert_called_once()

    @patch('stt.os.path.isfile', return_value=True)
    @patch('stt.WhisperModel')
    def test_transcribe_empty_audio(self, mock_model_cls, _mock_isfile):
        from stt import Stt
        mock_model = mock_model_cls.return_value
        mock_model.transcribe.return_value = (iter([]), fake_info())
        stt = Stt({'local_files_only': True})
        text, confidence = stt.transcribe_file('/tmp/silence.wav')
        self.assertEqual(text, '')
        self.assertIsNone(confidence['avg_log_prob'])
        self.assertIsNone(confidence['no_speech_prob'])


if __name__ == '__main__':
    unittest.main()
