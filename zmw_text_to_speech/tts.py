import glob
import hashlib
import os
import subprocess
import tempfile
import time
import wave

from piper.voice import PiperVoice

from zzmw_lib.logs import build_logger

log = build_logger("Tts")


def _parse_voice_id(voice_id):
    """Parse voice_id like 'en_US-lessac-medium' into (lang, locale, name, quality)."""
    parts = voice_id.split('-')
    locale = parts[0]       # en_US
    name = parts[1]         # lessac
    quality = parts[2] if len(parts) > 2 else 'unknown'
    lang = locale.split('_')[0]  # en
    return lang, locale, name, quality


class Tts:
    def __init__(self, cfg):
        self._default_language = cfg.get('default_language', 'en')
        self._output_dir = cfg.get('output_dir', tempfile.gettempdir())
        os.makedirs(self._output_dir, exist_ok=True)

        model_dir = cfg.get('model_dir', './tts_model')
        defaults = cfg.get('defaults', {})

        # Discover and load all .onnx models
        self._voices = {}       # voice_id -> PiperVoice
        self._voice_info = {}   # voice_id -> (lang, locale, name, quality)
        self._by_locale = {}    # locale -> [voice_id, ...] sorted
        self._by_lang = {}      # lang -> [voice_id, ...] sorted

        onnx_files = sorted(glob.glob(os.path.join(model_dir, '*.onnx')))
        onnx_files = [f for f in onnx_files if not f.endswith('.onnx.json')]
        if not onnx_files:
            raise ValueError(f"No .onnx models found in {model_dir}")

        for path in onnx_files:
            voice_id = os.path.basename(path).removesuffix('.onnx')
            lang, locale, name, quality = _parse_voice_id(voice_id)
            log.info("Loading voice '%s' from %s", voice_id, path)
            self._voices[voice_id] = PiperVoice.load(path)
            self._voice_info[voice_id] = (lang, locale, name, quality)
            self._by_locale.setdefault(locale, []).append(voice_id)
            self._by_lang.setdefault(lang, []).append(voice_id)

        # Build defaults: explicit config overrides, then first voice per lang/locale
        self._defaults = {}
        for key in list(self._by_lang) + list(self._by_locale):
            if key not in self._defaults:
                pool = self._by_locale.get(key) or self._by_lang.get(key)
                self._defaults[key] = pool[0]
        for key, voice_id in defaults.items():
            if voice_id in self._voices:
                self._defaults[key] = voice_id
            else:
                log.warning("Default voice '%s' for '%s' not found, ignoring", voice_id, key)

        log.info("TTS loaded %d voices, defaults: %s", len(self._voices), self._defaults)

    def get_voices(self):
        """Return list of available voices with metadata."""
        # Invert defaults: voice_id -> list of keys it's default for
        default_for = {}
        for key, vid in self._defaults.items():
            default_for.setdefault(vid, []).append(key)

        fallback_vid = self._defaults.get(self._default_language)

        voices = []
        for voice_id, (lang, locale, name, quality) in sorted(self._voice_info.items()):
            entry = {
                'voice_id': voice_id,
                'name': name.title(),
                'locale': locale,
                'lang': lang,
                'quality': quality,
            }
            if voice_id in default_for:
                entry['default_for'] = sorted(default_for[voice_id])
            if voice_id == fallback_vid:
                entry['default_fallback'] = True
            voices.append(entry)
        return voices

    def resolve_voice(self, language=None, speaker=None):
        """Resolve a voice_id from language/speaker params. Returns (voice_id, PiperVoice)."""
        if speaker and speaker in self._voices:
            return speaker, self._voices[speaker]

        lang_key = language or self._default_language
        # Try exact match first (e.g. "en_US"), then language-only (e.g. "en")
        for key in [lang_key, lang_key.split('_')[0]]:
            if key in self._defaults:
                vid = self._defaults[key]
                return vid, self._voices[vid]

        log.warning("No voice for language '%s', falling back to default '%s'",
                    lang_key, self._default_language)
        vid = self._defaults.get(self._default_language)
        if vid:
            return vid, self._voices[vid]

        # Last resort: first voice
        vid = sorted(self._voices)[0]
        return vid, self._voices[vid]

    def synthesize(self, text, language=None, speaker=None):
        """Synthesize text to an mp3 file. Returns (mp3_path, voice_id)."""
        voice_id, voice = self.resolve_voice(language, speaker)
        log.info("Synthesizing (voice=%s): '%s'", voice_id, text[:80])

        t0 = time.monotonic()
        text_hash = hashlib.md5(f"{text}:{voice_id}".encode()).hexdigest()[:12]
        wav_path = os.path.join(self._output_dir, f"tts_{text_hash}.wav")
        mp3_path = os.path.join(self._output_dir, f"tts_{text_hash}.mp3")

        with wave.open(wav_path, 'wb') as wav_file:
            voice.synthesize_wav(text, wav_file)

        subprocess.run(
            ['ffmpeg', '-y', '-i', wav_path, '-q:a', '2', mp3_path],
            check=True, capture_output=True)
        os.remove(wav_path)

        elapsed = time.monotonic() - t0
        log.info("TTS completed in %.2fs: %s", elapsed, mp3_path)
        return mp3_path, voice_id


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} TEXT...")
        sys.exit(1)

    text = ' '.join(sys.argv[1:])
    tts = Tts({'model_dir': './tts_model', 'default_language': 'en'})
    for speaker in tts.get_voices():
        vid = speaker['voice_id']
        path, _ = tts.synthesize(text, speaker=vid)
        print(f"{vid}: {path}")
