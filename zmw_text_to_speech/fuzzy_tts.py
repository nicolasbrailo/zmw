import os
import threading

from zzmw_lib.logs import build_logger

log = build_logger("FuzzyTts")

_SYSTEM_PROMPT = (
    "Rephrase the following message in your own words. "
    "You are: {personality}. "
    "Keep the same meaning and language. "
    "Reply with ONLY the rephrased text, nothing else."
)


class _LazyLlama:
    """Thread-safe lazy-loading wrapper for llama_cpp.Llama."""
    def __init__(self, **kwargs):
        self._kwargs = kwargs
        self._llm = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._load, daemon=True)
        self._thread.start()

    def _load(self):
        try:
            from llama_cpp import Llama
            log.info("Loading fuzzy TTS model '%s'...", self._kwargs.get('model_path'))
            llm = Llama(**self._kwargs)
            with self._lock:
                self._llm = llm
            log.info("Fuzzy TTS model loaded")
        except Exception:
            log.exception("Failed to load fuzzy TTS model")

    def create_chat_completion(self, **kwargs):
        with self._lock:
            if self._llm is None:
                return None
            return self._llm.create_chat_completion(**kwargs)


class FuzzyTts:
    def __init__(self, model_path, temperature=0.9):
        if not model_path or not os.path.isfile(model_path):
            log.warning("Fuzzy TTS model not found at '%s', fuzzy mode disabled", model_path)
            self._llm = None
            return
        # Higher temperature = more varied/creative paraphrases, lower = more predictable.
        # 0.9 is a good default for personality-driven style transfer.
        self._temperature = temperature
        self._llm = _LazyLlama(model_path=model_path, n_ctx=256, verbose=False)

    def paraphrase(self, text, personality):
        """Paraphrase text according to personality. Returns paraphrased string, or None on failure."""
        if self._llm is None:
            return None
        try:
            result = self._llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT.format(personality=personality)},
                    {"role": "user", "content": text},
                ],
                max_tokens=80,
                temperature=self._temperature,
            )
            if result is None:
                return None
            output = result['choices'][0]['message']['content']
            return output.strip().strip('"\'')
        except Exception:
            log.exception("Fuzzy TTS paraphrase failed")
            return None
