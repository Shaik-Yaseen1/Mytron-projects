#!/usr/bin/env python3
"""Unified launcher for all Mytron data-pipeline scripts.

Run it with no arguments and pick an operation from the menu:

    python3 run.py

Each option just collects the inputs it needs and then hands off to the
underlying script in ``scripts/`` (or the ``egometa`` package), so the
individual tools stay usable on their own too.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
PY = sys.executable or "python3"


# ── small prompt helpers ─────────────────────────────────────────────────────
def ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{label}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def ask_path(label: str, *, must_exist: bool = True, allow_empty: bool = False) -> str:
    while True:
        raw = ask(label)
        if not raw:
            if allow_empty:
                return ""
            print("  A path is required.")
            continue
        path = Path(raw).expanduser()
        if must_exist and not path.exists():
            print(f"  Path does not exist: {path}")
            continue
        return str(path)


def ask_yes_no(label: str, default: bool = False) -> bool:
    d = "y" if default else "n"
    return ask(f"{label} (y/n)", d).lower().startswith("y")


def run(cmd: list[str]) -> int:
    printable = " ".join(str(c) for c in cmd)
    print(f"\n→ {printable}\n" + "-" * 60, flush=True)
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


# ── operations ───────────────────────────────────────────────────────────────
def op_format_sd() -> int:
    """Format externally inserted removable SD cards (macOS, repeat cycle)."""
    print(
        "\nThis formats ALL external removable SD cards it lists — data is erased.\n"
        "The live table opens next; press Enter there to format, Ctrl+C to quit."
    )
    if not ask_yes_no("Continue?", default=False):
        return 0
    return run([PY, "-u", str(SCRIPTS / "format_sd.py")])


def op_build_to_mp4() -> int:
    """Rename/copy dashcam .build files to .mp4."""
    source = ask_path("Folder to scan for .build files (e.g. SD card mount)")
    out = ask_path(
        "Output folder (blank = rename in place)", must_exist=False, allow_empty=True
    )
    cmd = [PY, str(SCRIPTS / "build_to_mp4.py"), source]
    if out:
        cmd += ["-o", out]
    return run(cmd)


def op_count_mp4() -> int:
    """Count .mp4 files in a folder and total their size."""
    folder = ask_path("Folder to scan", allow_empty=True) or "."
    cmd = [PY, str(SCRIPTS / "count_mp4.py"), folder]
    if ask_yes_no("Include subfolders?", default=True):
        cmd.append("-r")
    return run(cmd)


def op_unzip() -> int:
    """Extract every .zip in a folder (safe: handles zip-slip, bad encodings)."""
    folder = ask_path("Folder containing .zip files", allow_empty=True) or "."
    cmd = [PY, str(SCRIPTS / "unzip_all.py"), folder]
    if ask_yes_no("Also search subfolders?", default=False):
        cmd.append("--recursive")
    if ask_yes_no("Delete each .zip after successful extract?", default=False):
        cmd.append("--delete")
    return run(cmd)


def op_upload_gcs() -> int:
    """Upload videos from a local folder to a Google Cloud Storage bucket."""
    if not shutil.which("gcloud"):
        print(
            "\ngcloud CLI not found. Install it and run `gcloud auth login` first:\n"
            "  https://cloud.google.com/sdk/docs/install"
        )
        return 1
    source = ask_path("Local folder containing videos")
    bucket = ask("Destination bucket name (without gs://)")
    if not bucket:
        print("  Bucket name is required.")
        return 1
    prefix = ask("Path prefix inside the bucket (optional)")
    cmd = ["bash", str(SCRIPTS / "upload_videos_to_gcs.sh"), "-s", source, "-b", bucket]
    if prefix:
        cmd += ["-p", prefix]
    project = ask("GCP project ID (blank = current gcloud config)")
    if project:
        cmd += ["-j", project]
    if ask_yes_no("Dry run (show what would upload, no changes)?", default=True):
        cmd.append("-n")
    elif ask_yes_no("Delete each local file after a verified upload?", default=False):
        cmd.append("-d")
    return run(cmd)


def op_metadata() -> int:
    """Generate VLM metadata JSON for egocentric video datasets."""
    parent = ask_path("Parent path (its subfolders are worker folders)")
    print("egometa will now prompt for company, city, backend, etc.")
    return run([PY, "-m", "egometa", "--parent-path", parent])


MENU: list[tuple[str, "callable[[], int]"]] = [
    ("Format SD card(s)            — erase & format external removable cards", op_format_sd),
    ("Convert .build -> .mp4       — fix dashcam/DVR file extensions", op_build_to_mp4),
    ("Count .mp4 files & size      — tally videos in a folder", op_count_mp4),
    ("Unzip all .zip files         — safe bulk extract", op_unzip),
    ("Upload videos to GCS         — push a folder to a Cloud Storage bucket", op_upload_gcs),
    ("Generate video metadata      — VLM-labeled metadata.json (egometa)", op_metadata),
]


def main() -> int:
    while True:
        print("\n" + "=" * 60)
        print("  Mytron data pipeline — pick an operation")
        print("=" * 60)
        for i, (label, _) in enumerate(MENU, start=1):
            print(f"  {i}. {label}")
        print("  0. Exit")

        choice = ask("\nOption")
        if choice in {"0", "q", "quit", "exit", ""}:
            return 0
        if not choice.isdigit() or not (1 <= int(choice) <= len(MENU)):
            print("  Enter a number from the list.")
            continue

        _, handler = MENU[int(choice) - 1]
        try:
            rc = handler()
        except KeyboardInterrupt:
            print("\nCancelled.")
            continue
        print("-" * 60)
        print("  Done." if rc == 0 else f"  Finished with exit code {rc}.")

        if not ask_yes_no("\nBack to menu?", default=True):
            return rc


if __name__ == "__main__":
    raise SystemExit(main())
