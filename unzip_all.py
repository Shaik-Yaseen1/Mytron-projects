#!/usr/bin/env python3
"""Unzip all .zip files found in a folder, safely and robustly.

Handles the common gotchas with real-world zip files:
- Corrupted/invalid archives (skipped, reported, don't stop the run)
- Zip-slip path traversal (entries like "../../etc/passwd" are rejected)
- Legacy filename encoding (zips made on Windows often store names as
  CP437 instead of UTF-8, which normally shows up as garbled characters)
"""

import argparse
import sys
import zipfile
from pathlib import Path


def decode_name(name: str) -> str:
    """Fix filenames mangled by zips that store CP437 instead of UTF-8."""
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def is_safe_member(target_dir: Path, member_name: str) -> bool:
    """Reject zip-slip entries that would extract outside target_dir."""
    resolved = (target_dir / member_name).resolve()
    return resolved == target_dir or target_dir in resolved.parents


def extract_zip(zip_path: Path, extract_dir: Path) -> bool:
    """Extract one zip file. Returns True on success."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad_entry = zf.testzip()
            if bad_entry is not None:
                print(f"  Corrupted entry in archive: {bad_entry}", file=sys.stderr)
                return False

            extract_dir.mkdir(parents=True, exist_ok=True)

            for info in zf.infolist():
                name = decode_name(info.filename)

                if not is_safe_member(extract_dir, name):
                    print(f"  Skipped unsafe path in archive: {info.filename}", file=sys.stderr)
                    continue

                dest = extract_dir / name
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue

                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    out.write(src.read())
        return True
    except zipfile.BadZipFile:
        print(f"  Not a valid zip file: {zip_path.name}", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"  Failed to extract {zip_path.name}: {exc}", file=sys.stderr)
        return False


def unzip_all(folder: Path, delete_after: bool = False, recursive: bool = False) -> None:
    pattern = "**/*.zip" if recursive else "*.zip"
    zip_files = sorted(folder.glob(pattern))

    if not zip_files:
        print(f"No zip files found in {folder}")
        return

    succeeded, failed = 0, 0

    for zip_path in zip_files:
        extract_dir = zip_path.parent / zip_path.stem
        print(f"Extracting {zip_path.relative_to(folder)} -> {extract_dir.relative_to(folder)}/")

        if extract_zip(zip_path, extract_dir):
            succeeded += 1
            if delete_after:
                zip_path.unlink()
                print("  Deleted source zip")
        else:
            failed += 1

    print(f"Done. {succeeded} extracted, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unzip all .zip files in a folder.")
    parser.add_argument(
        "folder",
        nargs="?",
        default=".",
        help="Path to the folder containing zip files (default: current directory)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete each zip file after successful extraction",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Also search subfolders for zip files",
    )
    args = parser.parse_args()

    target_folder = Path(args.folder).expanduser().resolve()
    if not target_folder.is_dir():
        print(f"Error: {target_folder} is not a valid directory", file=sys.stderr)
        sys.exit(1)

    unzip_all(target_folder, delete_after=args.delete, recursive=args.recursive)
