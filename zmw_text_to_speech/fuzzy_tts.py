import os
import threading

from zzmw_lib.logs import build_logger

log = build_logger("FuzzyTts")


def _build_messages(system_prompt, examples, text):
    # Examples are injected as user/assistant chat turns rather than inline in the system
    # prompt. Small models (1.5B) understand the chat turn format much better — inline
    # examples get regurgitated verbatim or used as a lookup table instead of learning
    # the style pattern.
    messages = [{"role": "system", "content": system_prompt}]
    for ex_in, ex_out in examples:
        messages.append({"role": "user", "content": ex_in})
        messages.append({"role": "assistant", "content": ex_out})
    messages.append({"role": "user", "content": text})
    return messages


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
        self._temperature = temperature
        self._llm = _LazyLlama(model_path=model_path, n_ctx=512, verbose=False)

    def paraphrase(self, text, system_prompt, examples=None):
        """Paraphrase text according to system_prompt and examples. Returns paraphrased string, or None on failure."""
        if self._llm is None:
            return None
        try:
            messages = _build_messages(system_prompt, examples or [], text)
            result = self._llm.create_chat_completion(
                messages=messages,
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
