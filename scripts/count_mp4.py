#!/usr/bin/env python3
"""Count .mp4 files in a folder and total their size."""

import argparse
import os


def human_readable_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def scan_mp4_files(folder, recursive=False):
    count = 0
    total_size = 0
    if recursive:
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".mp4"):
                    count += 1
                    total_size += os.path.getsize(os.path.join(root, f))
    else:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.lower().endswith(".mp4"):
                    count += 1
                    total_size += entry.stat().st_size
    return count, total_size


def main():
    parser = argparse.ArgumentParser(description="Count .mp4 files in a folder and total their size.")
    parser.add_argument("folder", nargs="?", default=".", help="Folder to search (default: current directory)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Include subfolders")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f"Error: '{args.folder}' is not a valid directory.")
        return

    count, total_size = scan_mp4_files(args.folder, args.recursive)
    scope = " (including subfolders)" if args.recursive else ""
    print(f"Found {count} .mp4 file(s) in '{args.folder}'{scope}.")
    print(f"Total size: {human_readable_size(total_size)}")


if __name__ == "__main__":
    main()
