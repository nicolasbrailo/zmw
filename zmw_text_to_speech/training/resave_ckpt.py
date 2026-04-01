#!/usr/bin/env python3
"""Re-save a PyTorch checkpoint to remove unpickling-unsafe globals (e.g. PosixPath)."""

import argparse
import pathlib
import torch


def strip_posixpaths(obj):
    """Recursively convert PosixPath instances to strings."""
    if isinstance(obj, pathlib.PurePath):
        return str(obj)
    if isinstance(obj, dict):
        return {k: strip_posixpaths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_posixpaths(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(strip_posixpaths(v) for v in obj)
    return obj


parser = argparse.ArgumentParser()
parser.add_argument("input", help="Path to original .ckpt file")
parser.add_argument("--output", help="Output path (default: overwrites input)")
args = parser.parse_args()

output = args.output or args.input

print(f"Loading {args.input} ...")
ckpt = torch.load(args.input, map_location="cpu", weights_only=False)
ckpt = strip_posixpaths(ckpt)
if "hyper_parameters" in ckpt:
    print(f"Removing {len(ckpt['hyper_parameters'])} saved hyper_parameters")
    del ckpt["hyper_parameters"]
print(f"Saving to {output} ...")
torch.save(ckpt, output)
print("Done.")
