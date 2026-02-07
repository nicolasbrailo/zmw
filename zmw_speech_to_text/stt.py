import io
import os
import time

from zzmw_lib.logs import build_logger

from faster_whisper import WhisperModel

log = build_logger("Stt")


class Stt:
    def __init__(self, cfg):
        model_size = cfg.get('model_size', 'tiny.en')
        compute_type = cfg.get('compute_type', 'int8')
        local_files_only = cfg['local_files_only']
        self._language = cfg.get('language', 'en')
        self._task = cfg.get('task', 'translate')
        self._beam_size = cfg.get('beam_size', 5)
        log.info("Loading whisper model '%s' (compute_type=%s, local_files_only=%s)",
                 model_size, compute_type, local_files_only)
        self._model = WhisperModel(model_size, compute_type=compute_type,
                                   download_root='./stt_model',
                                   local_files_only=local_files_only)
        log.info("Whisper STT model loaded")

    def transcribe_file(self, path):
        """Transcribe audio from a file path. Returns None if file doesn't exist."""
        if not os.path.isfile(path):
            log.warning("File not found, skipping transcription: %s", path)
            return None
        log.info("Transcribing file %s", path)
        return self._transcribe(path)

    def transcribe_bytes(self, audio_bytes):
        """Transcribe audio from raw bytes."""
        log.info("Transcribing %d bytes of audio", len(audio_bytes))
        return self._transcribe(io.BytesIO(audio_bytes))

    def _transcribe(self, source):
        t0 = time.monotonic()
        segments, info = self._model.transcribe(
            source,
            language=self._language,
            task=self._task,
            beam_size=self._beam_size,
        )
        seg_list = list(segments)
        text = " ".join(seg.text.strip() for seg in seg_list).strip()
        elapsed = time.monotonic() - t0

        if seg_list:
            avg_log_prob = sum(s.avg_logprob for s in seg_list) / len(seg_list)
            no_speech_prob = sum(s.no_speech_prob for s in seg_list) / len(seg_list)
        else:
            avg_log_prob = None
            no_speech_prob = None

        confidence = {
            'language': info.language,
            'language_prob': round(info.language_probability, 3),
            'avg_log_prob': round(avg_log_prob, 3) if avg_log_prob is not None else None,
            'no_speech_prob': round(no_speech_prob, 3) if no_speech_prob is not None else None,
        }

        log.info("Transcription completed in %.2fs (lang=%s lang_prob=%.3f avg_log_prob=%s no_speech_prob=%s): '%s'",
                 elapsed, confidence['language'], confidence['language_prob'],
                 confidence['avg_log_prob'], confidence['no_speech_prob'], text)
        return text, confidence
