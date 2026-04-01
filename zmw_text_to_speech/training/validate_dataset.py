#!/usr/bin/env python3
"""Validate a dataset produced by prepare_dataset.py.

Loads metadata.csv, re-transcribes each WAV clip with Whisper, and compares
the result to the stored transcript. Entries whose transcriptions don't match
are moved to the low_confidence/ subdirectory.

Usage:
  python validate_dataset.py dataset_dir [--model medium] [--language en]
                                         [--threshold 0.8]
"""

import argparse
import logging
import os
import shutil
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher


def load_metadata(csv_path):
    """Load metadata.csv and return list of (filename, text) tuples."""
    entries = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            if len(parts) < 2:
                print(f"Error: metadata.csv line {lineno}: bad format",
                      file=sys.stderr)
                sys.exit(1)
            entries.append((parts[0], parts[1]))
    return entries


def normalize(text):
    """Lowercase, strip punctuation and extra whitespace for comparison."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def similarity(a, b):
    """Return 0-1 similarity ratio between two strings."""
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def main():
    parser = argparse.ArgumentParser(
        description="Validate dataset by re-transcribing clips and checking against metadata"
    )
    parser.add_argument("dataset_dir", help="Path to dataset directory (contains metadata.csv and wavs/)")
    parser.add_argument("--language", default=None,
                        help="Language code for Whisper (auto-detected if omitted)")
    parser.add_argument("--model", default="medium",
                        help="Whisper model size (default: medium)")
    parser.add_argument("--threshold", type=float, default=0.8,
                        help="Similarity threshold 0-1 to consider a match (default: 0.8)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel transcription workers (default: 1)")

    args = parser.parse_args()

    csv_path = os.path.join(args.dataset_dir, "metadata.csv")
    if not os.path.isfile(csv_path):
        print(f"Error: '{csv_path}' not found", file=sys.stderr)
        sys.exit(1)

    entries = load_metadata(csv_path)
    if not entries:
        print("metadata.csv is empty — nothing to validate.")
        return

    print(f"Loaded {len(entries)} entries from metadata.csv")

    # Suppress Whisper's logging and FP16 warnings
    logging.getLogger("whisper").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")

    import whisper
    print(f"Loading Whisper model '{args.model}'...")
    model = whisper.load_model(args.model)

    good = []
    bad = []

    def transcribe_entry(filename, expected_text):
        wav_path = os.path.join(args.dataset_dir, filename + ".wav")
        if not os.path.isfile(wav_path):
            return filename, expected_text, None, "[file missing]"
        result = model.transcribe(wav_path, language=args.language, verbose=None)
        actual_text = result["text"].strip()
        score = similarity(expected_text, actual_text)
        return filename, expected_text, score, actual_text

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(transcribe_entry, fn, txt): i
            for i, (fn, txt) in enumerate(entries)
        }
        for future in as_completed(futures):
            filename, expected_text, score, actual_text = future.result()
            done += 1

            if score is None:
                print(f"  MISSING: {filename}", file=sys.stderr)
                bad.append((filename, expected_text, actual_text))
            elif score >= args.threshold:
                good.append((filename, expected_text))
            else:
                bad.append((filename, expected_text, actual_text))
                print(f"  MISMATCH ({score:.0%}): {filename}")
                print(f"    expected: {expected_text}")
                print(f"    got:      {actual_text}")

            if done % 20 == 0 or done == len(entries):
                print(f"  Validated {done}/{len(entries)}")

    if not bad:
        print(f"\nAll {len(good)} entries match. Dataset is clean.")
        return

    # Rewrite metadata.csv with only good entries
    with open(csv_path, "w", encoding="utf-8") as f:
        for filename, text in good:
            f.write(f"{filename}|{text}\n")

    # Move bad entries to low_confidence
    low_dir = os.path.join(args.dataset_dir, "low_confidence")
    low_wavs = os.path.join(low_dir, "wavs")
    os.makedirs(low_wavs, exist_ok=True)

    low_csv_path = os.path.join(low_dir, "metadata.csv")
    with open(low_csv_path, "a", encoding="utf-8") as f:
        for filename, expected_text, actual_text in bad:
            src = os.path.join(args.dataset_dir, filename + ".wav")
            if os.path.isfile(src):
                dst = os.path.join(low_dir, filename + ".wav")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            f.write(f"{filename}|{expected_text}\n")

    print(f"\nDone! {len(good)} good, {len(bad)} moved to low_confidence/")
    print(f"  Updated {csv_path} ({len(good)} entries)")
    print(f"  Appended {len(bad)} entries to {low_csv_path}")


if __name__ == "__main__":
    main()
