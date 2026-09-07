#!/usr/bin/env python3
"""Rename dashcam/DVR .build files (already MP4 data, wrong extension) to .mp4.

Usage:
    python3 build_to_mp4.py /Volumes/APERTURE [-o /path/to/output]

By default files are renamed in place (instant, no copy). Pass -o/--output
to copy them into a separate folder as .mp4 instead (mirroring the source's
relative subfolders), leaving the originals untouched.

Only .build files are touched. Any .txt/.a files sitting alongside them are
left exactly as-is.
"""

import argparse
import shutil
import sys
from pathlib import Path


def find_build_files(root: Path):
    return sorted(root.rglob("*.build"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="Folder to scan for .build files (e.g. the SD card mount point)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Copy into this folder as .mp4 instead of renaming in place")
    args = parser.parse_args()

    if not args.source.exists():
        sys.exit(f"Source path does not exist: {args.source}")

    files = find_build_files(args.source)
    if not files:
        sys.exit(f"No .build files found under {args.source}")

    print(f"Found {len(files)} .build file(s) under {args.source}")

    ok, failed = 0, 0
    for src in files:
        if args.output:
            rel = src.relative_to(args.source)
            dst = (args.output / rel).with_suffix(".mp4")
            dst.parent.mkdir(parents=True, exist_ok=True)
            action = "Copying"
        else:
            dst = src.with_suffix(".mp4")
            action = "Renaming"

        print(f"{action}: {src} -> {dst}")
        try:
            if args.output:
                shutil.copy2(src, dst)
            else:
                src.rename(dst)
            ok += 1
        except OSError as e:
            print(f"  FAILED: {e}")
            failed += 1

    print(f"\nDone. {ok} converted, {failed} failed.")


if __name__ == "__main__":
    main()
