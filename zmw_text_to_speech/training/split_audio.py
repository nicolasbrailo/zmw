#!/usr/bin/env python3
# sudo apt-get install python3-soundfile python3-soxr

"""Split a long WAV recording into sentence-sized clips using RMS silence detection.

Detects silence regions in the audio, splits at those points, trims excess
silence, and adds consistent padding from the original audio.

Outputs:
  <output_dir>/wavs/0001.wav, 0002.wav, ...

Usage:
  python split_audio.py input.wav output_dir [--silence-thresh -50]
                                             [--min-silence 0.4]
                                             [--max-duration 10]
                                             [--pad 0.1]
"""

import argparse
import os
import sys

import numpy as np
import soundfile as sf


def read_audio(path):
    """Read audio file, return mono float32 samples and sample rate."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    return mono, sr


def rms_energy(samples, window_size, hop_size=None):
    """Compute RMS energy with a strided window. Returns one value per hop."""
    if hop_size is None:
        hop_size = window_size

    n = len(samples)
    if n < window_size:
        return np.array([np.sqrt(np.mean(samples ** 2))])

    n_frames = 1 + (n - window_size) // hop_size
    shape = (n_frames, window_size)
    strides = (samples.strides[0] * hop_size, samples.strides[0])
    frames = np.lib.stride_tricks.as_strided(samples, shape=shape,
                                             strides=strides)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def find_silence_regions(samples, sr, silence_thresh_db, min_silence_sec):
    """Find contiguous regions where RMS is below threshold.

    Returns list of (start_sample, end_sample) for each silence region.
    """
    hop = int(sr * 0.02)
    window = hop
    rms = rms_energy(samples, window, hop)

    thresh_linear = 10 ** (silence_thresh_db / 20)
    is_silent = rms < thresh_linear

    min_silence_frames = int(min_silence_sec * sr / hop)

    regions = []
    in_silence = False
    start = 0

    for i in range(len(is_silent)):
        if is_silent[i] and not in_silence:
            start = i
            in_silence = True
        elif not is_silent[i] and in_silence:
            if i - start >= min_silence_frames:
                regions.append((start * hop, i * hop))
            in_silence = False

    if in_silence and len(is_silent) - start >= min_silence_frames:
        regions.append((start * hop, min(len(is_silent) * hop, len(samples))))

    return regions


def split_at_silences(samples, sr, silence_regions):
    """Split audio at the midpoints of silence regions.

    Returns list of (start_sample, end_sample) for each chunk.
    """
    if not silence_regions:
        return [(0, len(samples))]

    cuts = []
    for start, end in silence_regions:
        mid = (start + end) // 2
        cuts.append(mid)

    chunks = []
    prev = 0
    for cut in cuts:
        if cut > prev:
            chunks.append((prev, cut))
        prev = cut
    if prev < len(samples):
        chunks.append((prev, len(samples)))

    return chunks


def trim_silence(samples, sr, silence_thresh_db):
    """Trim leading and trailing silence from a chunk. Returns (start, end) sample offsets."""
    hop = int(sr * 0.02)
    window = hop
    if len(samples) < window:
        return 0, len(samples)

    rms = rms_energy(samples, window, hop)
    thresh_linear = 10 ** (silence_thresh_db / 20)
    voiced = np.where(rms >= thresh_linear)[0]

    if len(voiced) == 0:
        return 0, len(samples)

    start = int(voiced[0]) * hop
    end = min(int(voiced[-1] + 1) * hop, len(samples))
    return start, end


def process_chunks(samples, sr, silence_thresh_db, min_silence_sec,
                   max_duration, pad_seconds):
    """Full pipeline: split, merge short chunks, re-split long ones, trim, pad.

    Returns list of numpy arrays, one per final chunk.
    """
    silence_regions = find_silence_regions(samples, sr, silence_thresh_db,
                                          min_silence_sec)
    raw_chunks = split_at_silences(samples, sr, silence_regions)

    # Merge short chunks (< 1s) with the previous chunk
    min_samples = int(sr * 1.0)
    merged_chunks = []
    for start, end in raw_chunks:
        if merged_chunks and (end - start) < min_samples:
            prev_start, _ = merged_chunks[-1]
            merged_chunks[-1] = (prev_start, end)
        else:
            merged_chunks.append((start, end))

    max_samples = int(sr * max_duration)
    retry_silence_sec = min_silence_sec / 2

    # Re-split any chunk that exceeds max_duration (including merged ones)
    split_chunks = []
    for start, end in merged_chunks:
        chunk = samples[start:end]
        if len(chunk) > max_samples:
            sub_regions = find_silence_regions(chunk, sr, silence_thresh_db,
                                              retry_silence_sec)
            sub_chunks = split_at_silences(chunk, sr, sub_regions)
            for s, e in sub_chunks:
                split_chunks.append(chunk[s:e])
        else:
            split_chunks.append(chunk)

    # Trim and pad with original audio (not silence)
    pad_samples = int(sr * pad_seconds)
    final_chunks = []
    for chunk in split_chunks:
        t_start, t_end = trim_silence(chunk, sr, silence_thresh_db)
        if t_end - t_start < int(sr * 0.1):
            continue
        p_start = max(0, t_start - pad_samples)
        p_end = min(len(chunk), t_end + pad_samples)
        final_chunks.append(chunk[p_start:p_end])

    return final_chunks


def save_chunks(chunks, sr, wavs_dir, start_index):
    """Write each chunk as a 22050 Hz mono 16-bit WAV."""
    import soxr

    paths = []
    target_sr = 22050
    for i, chunk in enumerate(chunks):
        idx = start_index + i + 1
        out_path = os.path.join(wavs_dir, f"{idx:04d}.wav")

        if sr != target_sr:
            resampled = soxr.resample(chunk, sr, target_sr)
        else:
            resampled = chunk

        sf.write(out_path, resampled, target_sr, subtype="PCM_16")
        paths.append(out_path)

        if (i + 1) % 50 == 0 or i == len(chunks) - 1:
            print(f"  Saved {i + 1}/{len(chunks)} clips")

    return paths


def count_existing_wavs(wavs_dir):
    """Count existing wav files to determine start index for new ones."""
    if not os.path.isdir(wavs_dir):
        return 0
    return len([f for f in os.listdir(wavs_dir) if f.endswith(".wav")])


def main():
    parser = argparse.ArgumentParser(
        description="Split a long WAV into sentence clips using silence detection"
    )
    parser.add_argument("input_wav", help="Path to input WAV file")
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument("--silence-thresh", type=float, default=-50,
                        help="Silence threshold in dB (default: -50)")
    parser.add_argument("--min-silence", type=float, default=0.4,
                        help="Min silence duration in seconds for a cut (default: 0.4)")
    parser.add_argument("--max-duration", type=float, default=10,
                        help="Max chunk duration in seconds before re-splitting (default: 10)")
    parser.add_argument("--pad", type=float, default=0.1,
                        help="Padding from original audio added to each side after trimming (default: 0.1)")

    args = parser.parse_args()

    if not os.path.isfile(args.input_wav):
        print(f"Error: '{args.input_wav}' not found", file=sys.stderr)
        sys.exit(1)

    wavs_dir = os.path.join(args.output_dir, "wavs")
    os.makedirs(wavs_dir, exist_ok=True)

    start_index = count_existing_wavs(wavs_dir)
    if start_index:
        print(f"Found {start_index} existing wavs, continuing from {start_index + 1:04d}")

    print(f"Reading '{args.input_wav}'...")
    samples, sr = read_audio(args.input_wav)
    duration = len(samples) / sr
    print(f"  {duration:.1f}s at {sr} Hz")

    print(f"Detecting silence regions (thresh={args.silence_thresh} dB, "
          f"min_silence={args.min_silence}s)...")
    chunks = process_chunks(samples, sr, args.silence_thresh,
                            args.min_silence, args.max_duration, args.pad)
    print(f"  {len(chunks)} chunks after splitting")

    if not chunks:
        print("No speech chunks found — nothing to do.", file=sys.stderr)
        sys.exit(1)

    print(f"Saving {len(chunks)} clips (starting at {start_index + 1:04d})...")
    save_chunks(chunks, sr, wavs_dir, start_index)

    total = start_index + len(chunks)
    print(f"\nDone! {len(chunks)} new clips, {total} total in '{wavs_dir}/'")


if __name__ == "__main__":
    main()
