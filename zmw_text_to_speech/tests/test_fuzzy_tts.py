import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class TestFuzzyTtsDisabled(unittest.TestCase):
    def test_none_model_path(self):
        from fuzzy_tts import FuzzyTts
        ft = FuzzyTts(None)
        self.assertIsNone(ft.paraphrase("hello", "a pirate"))

    def test_empty_model_path(self):
        from fuzzy_tts import FuzzyTts
        ft = FuzzyTts("")
        self.assertIsNone(ft.paraphrase("hello", "a pirate"))

    def test_nonexistent_model_path(self):
        from fuzzy_tts import FuzzyTts
        ft = FuzzyTts("/no/such/file.gguf")
        self.assertIsNone(ft.paraphrase("hello", "a pirate"))


class TestFuzzyTtsParaphrase(unittest.TestCase):
    def _make_fuzzy_tts(self, llm_response):
        """Create a FuzzyTts with a mocked LLM that returns llm_response."""
        from fuzzy_tts import FuzzyTts
        with tempfile.NamedTemporaryFile(suffix='.gguf', delete=False) as f:
            fake_model = f.name

        try:
            with patch('fuzzy_tts._LazyLlama') as mock_llama_cls:
                mock_llm = MagicMock()
                mock_llm.create_chat_completion.return_value = llm_response
                mock_llama_cls.return_value = mock_llm
                ft = FuzzyTts(fake_model)
                ft._llm = mock_llm
                return ft
        finally:
            os.unlink(fake_model)

    def test_successful_paraphrase(self):
        ft = self._make_fuzzy_tts({
            'choices': [{'message': {'content': 'Ahoy, grub time!'}}]
        })
        result = ft.paraphrase("dinner is ready", "a pirate")
        self.assertEqual(result, "Ahoy, grub time!")

    def test_strips_quotes(self):
        ft = self._make_fuzzy_tts({
            'choices': [{'message': {'content': '"Time to eat!"'}}]
        })
        result = ft.paraphrase("dinner is ready", "a pirate")
        self.assertEqual(result, "Time to eat!")

    def test_strips_whitespace(self):
        ft = self._make_fuzzy_tts({
            'choices': [{'message': {'content': '  Grub time!  '}}]
        })
        result = ft.paraphrase("dinner is ready", "a pirate")
        self.assertEqual(result, "Grub time!")

    def test_llm_not_loaded_returns_none(self):
        ft = self._make_fuzzy_tts(None)
        ft._llm = MagicMock()
        ft._llm.create_chat_completion.return_value = None
        self.assertIsNone(ft.paraphrase("hello", "a pirate"))

    def test_llm_exception_returns_none(self):
        ft = self._make_fuzzy_tts(None)
        ft._llm = MagicMock()
        ft._llm.create_chat_completion.side_effect = RuntimeError("boom")
        self.assertIsNone(ft.paraphrase("hello", "a pirate"))

    def test_custom_temperature(self):
        from fuzzy_tts import FuzzyTts
        with tempfile.NamedTemporaryFile(suffix='.gguf', delete=False) as f:
            fake_model = f.name

        try:
            with patch('fuzzy_tts._LazyLlama'):
                ft = FuzzyTts(fake_model, temperature=0.3)
                self.assertEqual(ft._temperature, 0.3)
        finally:
            os.unlink(fake_model)

    def test_temperature_passed_to_llm(self):
        from fuzzy_tts import FuzzyTts
        with tempfile.NamedTemporaryFile(suffix='.gguf', delete=False) as f:
            fake_model = f.name

        try:
            with patch('fuzzy_tts._LazyLlama'):
                ft = FuzzyTts(fake_model, temperature=0.5)
                mock_llm = MagicMock()
                mock_llm.create_chat_completion.return_value = {
                    'choices': [{'message': {'content': 'test'}}]
                }
                ft._llm = mock_llm
                ft.paraphrase("hello", "a pirate")
                call_kwargs = mock_llm.create_chat_completion.call_args[1]
                self.assertEqual(call_kwargs['temperature'], 0.5)
        finally:
            os.unlink(fake_model)


if __name__ == '__main__':
    unittest.main()
