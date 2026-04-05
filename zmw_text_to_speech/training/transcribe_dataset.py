#!/usr/bin/env python3

"""Transcribe wav clips and generate metadata.csv for Piper training.

Reads all wav files from <output_dir>/wavs/, transcribes each with Whisper,
filters out bad entries, and writes metadata.csv in LJSpeech pipe-delimited format.

Usage:
  python transcribe_dataset.py output_dir [--language en]
                                          [--model medium]
                                          [--workers N]
                                          [--min-words 3]
"""

import argparse
import glob
import logging
import os
import sys
import warnings

import whisper

# Suppress Whisper's FP16/FP32 warnings and tqdm progress bars
warnings.filterwarnings("ignore", module="whisper")
logging.getLogger("whisper").setLevel(logging.ERROR)
os.environ["TQDM_DISABLE"] = "1"


def transcribe_chunks(wav_paths, model_name, language):
    """Transcribe wav files sequentially with Whisper."""

    print(f"Loading Whisper model '{model_name}'...")
    model = whisper.load_model(model_name)

    # Detect language from first clip
    first_result = model.transcribe(wav_paths[0], language=language, verbose=False)
    expected_lang = first_result.get("language", language)
    print(f"  Detected language: {expected_lang}")

    text = first_result["text"].strip()
    print(f"[1/{len(wav_paths)}] {wav_paths[0]}: {text}")
    transcripts = [(wav_paths[0], text)]
    for i, path in enumerate(wav_paths[1:], 1):
        result = model.transcribe(path, language=language, verbose=False)
        detected = result.get("language", expected_lang)
        text = result["text"].strip()
        if detected != expected_lang:
            text = ""
        transcripts.append((path, text))
        print(f"[{i + 1}/{len(wav_paths)}] {path}: {text}")

    return transcripts


def write_metadata(wav_paths, transcripts, output_dir):
    """Write metadata.csv in LJSpeech format."""
    csv_path = os.path.join(output_dir, "metadata.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        for path, text in zip(wav_paths, transcripts):
            rel = os.path.relpath(path, output_dir)
            name = os.path.splitext(rel)[0]
            f.write(f"{name}|{text}\n")
    print(f"Wrote {csv_path} ({len(transcripts)} entries)")


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe wav clips and generate metadata.csv for Piper training"
    )
    parser.add_argument("output_dir", help="Dataset directory (containing wavs/)")
    parser.add_argument("--language", default=None,
                        help="Language code for Whisper (auto-detected if omitted)")
    parser.add_argument("--model", default="medium",
                        help="Whisper model size (default: medium)")
    parser.add_argument("--min-words", type=int, default=3,
                        help="Discard clips with fewer than this many words (default: 3)")

    args = parser.parse_args()

    wavs_dir = os.path.join(args.output_dir, "wavs")
    if not os.path.isdir(wavs_dir):
        print(f"Error: '{wavs_dir}' not found", file=sys.stderr)
        sys.exit(1)

    wav_paths = sorted(glob.glob(os.path.join(wavs_dir, "*.wav")))
    if not wav_paths:
        print(f"Error: no wav files in '{wavs_dir}'", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(wav_paths)} wav files in '{wavs_dir}'")

    transcripts = transcribe_chunks(wav_paths, args.model, args.language)

    # Filter out empty, wrong-language, or too-short transcripts
    valid = [(p, t) for p, t in transcripts
             if t and len(t.split()) >= args.min_words]
    skipped = len(wav_paths) - len(valid)
    if skipped:
        bad_dir = os.path.join(args.output_dir, "dataset_bad")
        os.makedirs(bad_dir, exist_ok=True)
        print(f"  Moving {skipped} bad clips to '{bad_dir}/'")
        valid_set = set(p for p, _ in valid)
        for p in wav_paths:
            if p not in valid_set:
                os.rename(p, os.path.join(bad_dir, os.path.basename(p)))
    wav_paths = [p for p, _ in valid]
    transcripts = [t for _, t in valid]

    write_metadata(wav_paths, transcripts, args.output_dir)

    print(f"\nDone! {len(transcripts)} entries in metadata.csv")


if __name__ == "__main__":
    main()
