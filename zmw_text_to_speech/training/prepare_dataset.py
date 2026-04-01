#!/usr/bin/env python3
"""Split a long WAV recording into sentence-sized clips with transcripts.

Uses OpenAI Whisper for transcription + sentence segmentation, then FFmpeg
to cut and resample each segment to Piper's required format (22050 Hz, mono, 16-bit).

Outputs:
  <output_dir>/wavs/0001.wav, 0002.wav, ...
  <output_dir>/metadata.csv   (LJSpeech pipe-delimited format)

Usage:
  python prepare_dataset.py input.wav output_dir [--language]
                                      [--model medium] [--pad 0.1]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


def transcribe(input_wav, model_name, language):
    """Run Whisper and return list of segments with start/end/text."""
    import whisper

    print(f"Loading Whisper model '{model_name}'...")
    model = whisper.load_model(model_name)

    print(f"Transcribing '{input_wav}'...")
    result = model.transcribe(
        input_wav,
        language=language,
        verbose=False,
    )

    segments = []
    for seg in result["segments"]:
        text = seg["text"].strip()
        if text:
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": text,
                "avg_logprob": seg.get("avg_logprob", 0.0),
                "no_speech_prob": seg.get("no_speech_prob", 0.0),
                "compression_ratio": seg.get("compression_ratio", 0.0),
            })

    print(f"Got {len(segments)} segments from Whisper.")
    return segments


def split_by_confidence(segments, max_logprob=-1.0, max_no_speech=0.6,
                        max_compression=2.4):
    """Partition segments into (good, low_confidence) based on Whisper scores."""
    good, low = [], []
    for seg in segments:
        if (seg["avg_logprob"] < max_logprob
                or seg["no_speech_prob"] > max_no_speech
                or seg["compression_ratio"] > max_compression):
            low.append(seg)
        else:
            good.append(seg)
    return good, low


def split_audio(input_wav, segments, wavs_dir, pad_seconds, start_index=0):
    """Cut input_wav into per-segment clips, resampled to Piper format."""
    for i, seg in enumerate(segments):
        idx = start_index + i + 1
        out_path = os.path.join(wavs_dir, f"{idx:04d}.wav")
        start = max(0.0, seg["start"] - pad_seconds)
        end = seg["end"] + pad_seconds
        duration = end - start

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", input_wav,
            "-ar", "22050",
            "-ac", "1",
            "-sample_fmt", "s16",
            "-loglevel", "error",
            out_path,
        ]
        subprocess.run(cmd, check=True)

        if (i + 1) % 50 == 0 or i == len(segments) - 1:
            print(f"  Split {i + 1}/{len(segments)} clips")


def validate_existing_dataset(output_dir):
    """Check that every entry in metadata.csv has a matching wav file.

    Returns the number of valid existing samples, or 0 if no metadata exists.
    Exits with an error if any wav file is missing.
    """
    csv_path = os.path.join(output_dir, "metadata.csv")
    if not os.path.isfile(csv_path):
        return 0

    entries = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            if len(parts) < 2:
                print(f"Error: metadata.csv line {lineno}: bad format", file=sys.stderr)
                sys.exit(1)
            entries.append(parts[0])

    missing = [e for e in entries if not os.path.isfile(os.path.join(output_dir, e + ".wav"))]
    if missing:
        print(f"Error: metadata.csv references {len(missing)} missing wav file(s):", file=sys.stderr)
        for m in missing[:10]:
            print(f"  {m}", file=sys.stderr)
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more", file=sys.stderr)
        sys.exit(1)

    print(f"Validated {len(entries)} existing samples in metadata.csv")
    return len(entries)


def write_metadata(segments, output_dir, start_index):
    """Append metadata.csv entries in LJSpeech format."""
    csv_path = os.path.join(output_dir, "metadata.csv")
    mode = "a" if start_index > 0 else "w"
    with open(csv_path, mode, encoding="utf-8") as f:
        for i, seg in enumerate(segments):
            idx = start_index + i + 1
            # Don't include extension, seems to be added automatically by piper
            filename = f"wavs/{idx:04d}"
            f.write(f"{filename}|{seg['text']}\n")
    total = start_index + len(segments)
    print(f"Wrote {csv_path} ({len(segments)} new, {total} total entries)")


def main():
    parser = argparse.ArgumentParser(
        description="Split a long WAV into sentence clips + metadata.csv for Piper training"
    )
    parser.add_argument("input_wav", help="Path to input WAV file")
    parser.add_argument("output_dir", help="Output directory (default: dataset)")
    parser.add_argument("--language", default=None,
                        help="Language code for Whisper (e.g. en, es). Auto-detected if omitted.")
    parser.add_argument("--model", default="medium",
                        help="Whisper model size (default: medium)")
    parser.add_argument("--pad", type=float, default=0.1,
                        help="Seconds of padding around each segment (default: 0.1)")

    args = parser.parse_args()

    if not os.path.isfile(args.input_wav):
        print(f"Error: '{args.input_wav}' not found", file=sys.stderr)
        sys.exit(1)

    wavs_dir = os.path.join(args.output_dir, "wavs")
    os.makedirs(wavs_dir, exist_ok=True)

    start_index = validate_existing_dataset(args.output_dir)

    all_segments = transcribe(args.input_wav, args.model, args.language)

    if not all_segments:
        print("No segments found — nothing to do.", file=sys.stderr)
        sys.exit(1)

    segments, low_conf = split_by_confidence(all_segments)

    print(f"Splitting {len(segments)} segments (starting at {start_index + 1:04d})...")
    split_audio(args.input_wav, segments, wavs_dir, args.pad, start_index)
    write_metadata(segments, args.output_dir, start_index)

    if low_conf:
        low_dir = os.path.join(args.output_dir, "low_confidence")
        low_wavs = os.path.join(low_dir, "wavs")
        os.makedirs(low_wavs, exist_ok=True)
        low_start = validate_existing_dataset(low_dir)
        print(f"Splitting {len(low_conf)} low-confidence segments...")
        split_audio(args.input_wav, low_conf, low_wavs, args.pad, low_start)
        write_metadata(low_conf, low_dir, low_start)

    total = start_index + len(segments)
    print(f"\nDone! Dataset in '{args.output_dir}/'")
    print(f"  {len(segments)} new clips, {total} total in wavs/")
    if low_conf:
        print(f"  {len(low_conf)} low-confidence clips in low_confidence/wavs/")
    print(f"  metadata.csv ready for piper_train.preprocess")


if __name__ == "__main__":
    main()
