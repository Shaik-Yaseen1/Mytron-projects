#!/usr/bin/env python3
"""
Auto-detect external ~2/4 TiB class SSD and >15 TiB HDD on macOS, copy top-level
folders from SSD to HDD with rsync (optional parallel rsync per folder, merge: existing
files on the HDD are not overwritten or removed unless --overwrite), then optionally
remove those folders on the SSD after explicit confirmation (Enter).
Hidden (dot-prefixed) top-level folders are not copied or deleted.
"""

from __future__ import annotations

import argparse
import math
import os
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Serializes stderr progress lines when multiple rsync processes run at once
_PROGRESS_LOCK = threading.Lock()

# Binary tebibytes (TiB) for SSD band; diskutil sizes are in bytes.
_TIB = 1024**4

# Consumer external SSDs: ~2 TB and ~4 TB classes (tweak if needed)
SSD_MIN_BYTES = int(1.5 * _TIB)
SSD_MAX_BYTES = int(5.2 * _TIB)
# When ignoring SolidState (USB enclosure quirk), only treat ~2 TB-sized disks as SSD
# so a 4 TB HDD is not mistaken for a 4 TB SSD.
SSD_RELAX_USB_MAX_BYTES = int(2.85 * _TIB)

# HDD: whole-disk capacity strictly above 15 TB (decimal, 10^12 bytes) — matches
# how large consumer drives are labeled (e.g. 16 TB ≈ 16e12 bytes).
_TB_DECIMAL = 1000**4
HDD_MIN_BYTES = 15 * _TB_DECIMAL
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

# GNU rsync --info=progress2 (overall transfer; bytes may include commas)
_RSYNC_PROGRESS_RE = re.compile(
    r"(?P<bytes>[\d,]+)\s+(?P<pct>\d+)%\s+(?P<rate>[\d.]+\s*[KMGT]?i?B/s)\s+(?P<eta>\d+:\d+(?::\d+)?)",
    re.IGNORECASE,
)
# openrsync / BSD --progress (per-file line; no commas)
_RSYNC_PROGRESS_LEGACY_RE = re.compile(
    r"(?P<bytes>\d+)\s+(?P<pct>\d+)%\s+(?P<rate>[\d.]+\s*[KMGT]?i?B/s)\s+(?P<eta>\d+:\d+:\d+|\d+:\d+)",
    re.IGNORECASE,
)


def _human_bytes(n: float) -> str:
    x = max(0.0, float(n))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if x < 1024.0 or unit == "PiB":
            if unit == "B":
                return f"{int(round(x))} B"
            return f"{x:.2f} {unit}"
        x /= 1024.0
    return f"{x:.2f} PiB"


def _fmt_eta(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--"
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _parse_rate_to_bps(rate_str: str) -> float | None:
    s = rate_str.strip().upper().replace(" ", "")
    m = re.match(r"(?P<num>[\d.]+)(?P<unit>[KMGT])?I?B/S", s)
    if not m:
        return None
    val = float(m.group("num"))
    u = m.group("unit") or "K"
    mult = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}.get(u, 1024)
    return val * mult


def _parse_rsync_progress_line(line: str) -> dict[str, Any] | None:
    m = _RSYNC_PROGRESS_RE.search(line) or _RSYNC_PROGRESS_LEGACY_RE.search(line)
    if not m:
        return None
    return {
        "bytes": int(m.group("bytes").replace(",", "")),
        "pct": int(m.group("pct")),
        "rate": m.group("rate").strip(),
        "eta": m.group("eta"),
    }


def _rsync_supports_info_progress2() -> bool:
    try:
        out = subprocess.check_output(["rsync", "--help"], stderr=subprocess.STDOUT, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False
    return "progress2" in out


def _progress_bar(pct: float, width: int = 22) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = min(width, int(round(width * pct / 100.0)))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _du_bytes(path: Path) -> int:
    try:
        out = subprocess.check_output(
            ["du", "-sk", str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=7200,
        )
        kb = int(out.split()[0])
        return kb * 1024
    except (subprocess.CalledProcessError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0


def _run_rsync_progress2_stderr(
    cmd: list[str],
    *,
    label: str,
    total_bytes: int,
    parallel: bool = False,
) -> None:
    """GNU rsync: parse --info=progress2 on stderr."""
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert p.stderr is not None
    stderr = p.stderr
    buf = b""
    started = time.monotonic()
    last_render = 0.0
    tag = label[:36]

    def render(parsed: dict[str, Any] | None) -> None:
        nonlocal last_render
        now = time.monotonic()
        if parsed is None:
            return
        pct_val = int(parsed["pct"])
        if now - last_render < 0.12 and pct_val < 99:
            return
        last_render = now

        xfer = int(parsed["bytes"])
        pct_f = float(parsed["pct"])
        rate_raw = parsed["rate"]
        rate_compact = re.sub(r"\s+", "", rate_raw)
        eta_display = parsed["eta"]
        bps = _parse_rate_to_bps(rate_raw)
        if bps and total_bytes > 0 and xfer < total_bytes:
            alt = (total_bytes - xfer) / bps
            if math.isfinite(alt) and alt >= 0:
                if eta_display in ("0:00", "0:00:00") and alt > 2:
                    eta_display = _fmt_eta(alt)

        elapsed = time.monotonic() - started
        bar = _progress_bar(pct_f)
        tot_s = _human_bytes(total_bytes) if total_bytes > 0 else "?"
        if parallel:
            msg = (
                f"[{tag}] {bar} {pct_f:5.1f}%  "
                f"{_human_bytes(xfer)} / ~{tot_s}  {rate_compact}  "
                f"ETA {eta_display}  elapsed {_fmt_eta(elapsed)}"
            )
            with _PROGRESS_LOCK:
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
        else:
            msg = (
                f"\r{label[:42]:<42} {bar} {pct_f:5.1f}%  "
                f"{_human_bytes(xfer)} / ~{tot_s}  {rate_compact}  "
                f"ETA {eta_display}  elapsed {_fmt_eta(elapsed)}   "
            )
            sys.stderr.write(msg)
            sys.stderr.flush()

    while True:
        chunk = stderr.read(4096)
        if not chunk:
            break
        buf += chunk
        while True:
            if b"\r" in buf:
                part, _, buf = buf.partition(b"\r")
                line = part.decode("utf-8", errors="replace").strip()
                if line:
                    parsed = _parse_rsync_progress_line(line)
                    if parsed:
                        render(parsed)
            elif b"\n" in buf:
                part, _, buf = buf.partition(b"\n")
                line = part.decode("utf-8", errors="replace").strip()
                if line:
                    parsed = _parse_rsync_progress_line(line)
                    if parsed:
                        render(parsed)
            else:
                break

    if buf.strip():
        line = buf.decode("utf-8", errors="replace").strip()
        parsed = _parse_rsync_progress_line(line)
        if parsed:
            render(parsed)

    p.wait()
    if not parallel:
        sys.stderr.write("\n")
        sys.stderr.flush()
    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd)


def _run_rsync_du_poll_fallback(
    cmd: list[str],
    *,
    label: str,
    total_bytes: int,
    dst: Path,
    parallel: bool = False,
) -> None:
    """No GNU progress2: poll destination size growth vs source total (approximate)."""
    dst_before = _du_bytes(dst) if dst.exists() else 0
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started = time.monotonic()
    last_delta = 0
    last_t = started
    first = True
    tag = label[:36]
    while p.poll() is None:
        if not first:
            time.sleep(2.0)
        first = False
        now = time.monotonic()
        dst_now = _du_bytes(dst) if dst.exists() else dst_before
        delta = max(0, dst_now - dst_before)
        pct_f = min(99.9, 100.0 * delta / total_bytes) if total_bytes > 0 else 0.0
        rate_bps = (delta - last_delta) / max(1e-6, now - last_t)
        last_delta, last_t = delta, now
        eta_s: float | None = None
        if rate_bps > 1e-6 and total_bytes > delta:
            eta_s = (total_bytes - delta) / rate_bps
        eta_str = _fmt_eta(eta_s) if eta_s is not None and math.isfinite(eta_s) else "--:--"
        rate_str = f"{_human_bytes(rate_bps)}/s" if rate_bps > 0 else "…"
        bar = _progress_bar(pct_f)
        tot_s = _human_bytes(total_bytes) if total_bytes > 0 else "?"
        if parallel:
            msg = (
                f"[{tag}] {bar} {pct_f:5.1f}%  "
                f"{_human_bytes(delta)} / ~{tot_s}  {rate_str}  "
                f"ETA {eta_str}  elapsed {_fmt_eta(now - started)}"
            )
            with _PROGRESS_LOCK:
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
        else:
            msg = (
                f"\r{label[:42]:<42} {bar} {pct_f:5.1f}%  "
                f"{_human_bytes(delta)} / ~{tot_s}  {rate_str}  "
                f"ETA {eta_str}  elapsed {_fmt_eta(now - started)}   "
            )
            sys.stderr.write(msg)
            sys.stderr.flush()

    p.wait()
    now = time.monotonic()
    dst_now = _du_bytes(dst) if dst.exists() else dst_before
    delta = max(0, dst_now - dst_before)
    pct_f = min(100.0, 100.0 * delta / total_bytes) if total_bytes > 0 else 100.0
    bar = _progress_bar(pct_f)
    tot_s = _human_bytes(total_bytes) if total_bytes > 0 else "?"
    if parallel:
        msg = (
            f"[{tag}] {bar} {pct_f:5.1f}%  "
            f"{_human_bytes(delta)} / ~{tot_s}  done  "
            f"elapsed {_fmt_eta(now - started)}"
        )
        with _PROGRESS_LOCK:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
    else:
        msg = (
            f"\r{label[:42]:<42} {bar} {pct_f:5.1f}%  "
            f"{_human_bytes(delta)} / ~{tot_s}  done  "
            f"elapsed {_fmt_eta(now - started)}   \n"
        )
        sys.stderr.write(msg)
        sys.stderr.flush()
    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd)


def _run_rsync_with_progress(
    cmd: list[str],
    *,
    label: str,
    total_bytes: int,
    dst: Path,
    parallel: bool = False,
) -> None:
    """Run rsync with a terminal progress line (GNU progress2, else du-based estimate)."""
    cmd = list(cmd)
    try:
        i = cmd.index("-aHh") + 1
    except ValueError:
        i = 1
    if _rsync_supports_info_progress2():
        cmd.insert(i, "--info=progress2")
        _run_rsync_progress2_stderr(
            cmd,
            label=label,
            total_bytes=total_bytes,
            parallel=parallel,
        )
    else:
        _run_rsync_du_poll_fallback(
            cmd,
            label=label,
            total_bytes=total_bytes,
            dst=dst,
            parallel=parallel,
        )


def _run_plist(args: list[str]) -> dict[str, Any]:
    raw = subprocess.check_output(args, stderr=subprocess.STDOUT)
    return plistlib.loads(raw)


def _disk_info(device: str) -> dict[str, Any]:
    return _run_plist(["diskutil", "info", "-plist", device])


def _list_disks_plist() -> dict[str, Any]:
    return _run_plist(["diskutil", "list", "-plist"])


def _collect_mounts(
    node: Any,
    mounts: list[tuple[str, bool]],
) -> None:
    """Collect (MountPoint, OSInternal) from nested plist partition trees."""
    if isinstance(node, dict):
        mp = node.get("MountPoint")
        if isinstance(mp, str) and mp.startswith("/Volumes/"):
            internal = bool(node.get("OSInternal", False))
            mounts.append((mp, internal))
        for key in ("Partitions", "APFSVolumes"):
            if key in node:
                _collect_mounts(node[key], mounts)
    elif isinstance(node, list):
        for item in node:
            _collect_mounts(item, mounts)


def _mounts_for_whole_disk(plist: dict[str, Any], whole: str) -> list[str]:
    """Return non-internal /Volumes/* mount points for this whole disk id."""
    out: list[str] = []
    for top in plist.get("AllDisksAndPartitions", []):
        if not isinstance(top, dict):
            continue
        if top.get("DeviceIdentifier") != whole:
            continue
        collected: list[tuple[str, bool]] = []
        _collect_mounts(top, collected)
        for mp, os_int in collected:
            if not os_int:
                out.append(mp)
        break
    # Prefer a single stable order (longest path last could matter for nested; usually flat)
    return sorted(set(out))


def _external_whole_disks(
    plist: dict[str, Any],
) -> list[tuple[str, int, dict[str, Any]]]:
    """All external whole-disk devices (diskN) with size and diskutil info."""
    out: list[tuple[str, int, dict[str, Any]]] = []
    for whole in plist.get("WholeDisks", []):
        if not isinstance(whole, str):
            continue
        try:
            info = _disk_info(whole)
        except subprocess.CalledProcessError:
            continue
        if info.get("Internal"):
            continue
        if not info.get("WholeDisk", False):
            continue
        size = int(info.get("TotalSize") or info.get("Size") or 0)
        out.append((whole, size, info))
    out.sort(key=lambda x: x[1])
    return out


def _find_external_candidates(
    plist: dict[str, Any],
    *,
    want_ssd: bool,
    relaxed_solid: bool = False,
) -> list[tuple[str, int, dict[str, Any]]]:
    """
    Return list of (whole_disk_id, size_bytes, info_plist) matching criteria.

    SSD (want_ssd=True):
      - strict (relaxed_solid=False): SolidState + size in [SSD_MIN, SSD_MAX]
      - relaxed (relaxed_solid=True): ignore SolidState but only for sizes in
        [SSD_MIN, SSD_RELAX_USB_MAX] (~2 TB USB enclosures); larger drives need SolidState

    HDD (want_ssd=False):
      - strict: not SolidState + size > 15 TB decimal
      - relaxed: size > 15 TB only (ignore SolidState; some enclosures misreport)
    """
    matches: list[tuple[str, int, dict[str, Any]]] = []
    for whole, size, info in _external_whole_disks(plist):
        solid = bool(info.get("SolidState", False))
        if want_ssd:
            if relaxed_solid:
                if not (SSD_MIN_BYTES <= size <= SSD_RELAX_USB_MAX_BYTES):
                    continue
            else:
                if not (SSD_MIN_BYTES <= size <= SSD_MAX_BYTES):
                    continue
                if not solid:
                    continue
        else:
            if size <= HDD_MIN_BYTES:
                continue
            if not relaxed_solid and solid:
                continue
        matches.append((whole, size, info))
    # Stable order: larger disks first for HDD, smaller first for SSD
    matches.sort(key=lambda x: x[1], reverse=not want_ssd)
    return matches


def _print_external_disk_diagnostic(plist: dict[str, Any], *, for_ssd: bool) -> None:
    """Print external whole disks so the user can pick --ssd-disk / --hdd-disk."""
    rows = _external_whole_disks(plist)
    kind = "SSD" if for_ssd else "HDD"
    print(
        f"\nNo automatic {kind} match. External whole disks seen by diskutil:\n",
        file=sys.stderr,
    )
    if not rows:
        print(
            "  (none — drives must be mounted / connected; check Finder and USB.)\n",
            file=sys.stderr,
        )
        return
    for did, size, info in rows:
        solid = bool(info.get("SolidState", False))
        name = str(info.get("MediaName") or info.get("IORegistryEntryName") or "")[:56]
        size_str = f"{size / _TIB:.2f} TiB"
        print(
            f"  {did}  {size_str:>12}  SolidState={solid}  {name}",
            file=sys.stderr,
        )
    print(
        f"\nRun with the correct whole-disk id, e.g.:\n"
        f"  python3 {Path(__file__).resolve()} --ssd-disk diskN --hdd-disk diskM\n"
        f"(use `diskutil list` to confirm diskN; pick the physical disk, not a slice.)\n",
        file=sys.stderr,
    )


def _pick_one(
    label: str,
    items: list[tuple[str, int, dict[str, Any]]],
    manual: str | None,
    force_prompt: bool = False,
) -> tuple[str, int, dict[str, Any]]:
    if manual:
        info = _disk_info(manual)
        if not info.get("WholeDisk", False):
            sys.exit(f"--{label} must be a whole disk id (e.g. disk4), got {manual!r}")
        size = int(info.get("TotalSize") or info.get("Size") or 0)
        return manual, size, info
    if not items:
        sys.exit(
            f"No matching {label} found. Connect the drive or pass "
            f"--{label} diskN (see diskutil list)."
        )
    if len(items) == 1 and not force_prompt:
        return items[0]
    print(f"Select {label} from these candidates:")
    for i, (did, size, _) in enumerate(items, 1):
        print(f"  [{i}] {did}  ({size / _TIB:.2f} TiB)")
    choice = input("Enter number: ").strip()
    try:
        idx = int(choice) - 1
        return items[idx]
    except (ValueError, IndexError):
        sys.exit("Invalid selection.")


def _top_level_folders(root: Path) -> list[Path]:
    """Top-level non-symlink directories; skips hidden (dot-prefixed) folders."""
    if not root.is_dir():
        return []
    folders: list[Path] = []
    try:
        for p in root.iterdir():
            if p.is_dir() and not p.is_symlink():
                # Skip hidden folders (.Trashes, .Spotlight-V100, user .foo, etc.)
                if p.name.startswith("."):
                    continue
                folders.append(p)
    except OSError as e:
        sys.exit(f"Cannot read {root}: {e}")
    return sorted(folders, key=lambda x: x.name.lower())


def _build_rsync_cmd(src: Path, dst: Path, overwrite: bool) -> list[str]:
    """Local SSD→HDD copy: -W (whole-file) avoids delta algorithm and is faster for same-machine copies."""
    cmd = [
        "rsync",
        "-aHh",
        "-W",
        "--partial",
        str(src) + "/",
        str(dst) + "/",
    ]
    if not overwrite:
        cmd.insert(-2, "--ignore-existing")
    return cmd


def _fmt_duration_hms(total_seconds: float) -> str:
    secs = max(0, int(round(total_seconds)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _read_simple_env_file(env_path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE pairs from a .env file."""
    vals: dict[str, str] = {}
    if not env_path.exists():
        return vals
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return vals
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals


def _log_transfer_to_firestore(
    *,
    ssd_id: str,
    hdd_id: str,
    transfer_date: str,
    transfer_status: str,
    start_time: str,
    end_time: str,
    total_duration: str,
    script_dir: Path,
) -> None:
    """
    Write one transfer record to Firestore collection `HDD-transfer`.
    Uses FIREBASE_CREDENTIALS_PATH from env or local .env.
    """
    env_vals = _read_simple_env_file(script_dir / ".env")
    project_id = os.environ.get("FIREBASE_PROJECT_ID") or env_vals.get("FIREBASE_PROJECT_ID", "")
    cred_path_raw = os.environ.get("FIREBASE_CREDENTIALS_PATH") or env_vals.get("FIREBASE_CREDENTIALS_PATH", "")
    if not cred_path_raw:
        raise RuntimeError("FIREBASE_CREDENTIALS_PATH is missing in env/.env.")

    cred_path = Path(cred_path_raw).expanduser()
    if not cred_path.is_absolute():
        cred_path = (script_dir / cred_path).resolve()
    if not cred_path.exists():
        raise RuntimeError(f"Credentials file not found: {cred_path}")

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as e:
        raise RuntimeError(
            "firebase-admin is not installed. Install with: pip install firebase-admin"
        ) from e

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(cred_path))
        init_kwargs: dict[str, Any] = {"credential": cred}
        if project_id:
            init_kwargs["options"] = {"projectId": project_id}
        firebase_admin.initialize_app(**init_kwargs)

    db = firestore.client()
    doc = {
        "ssd_id": ssd_id,
        "hdd_id": hdd_id,
        "date": transfer_date,
        "transfer_status": transfer_status,
        "start_time": start_time,
        "end_time": end_time,
        "total_duration": total_duration,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.collection("HDD-transfer").add(doc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy top-level folders from ~2/4TB-class external SSD to >15TB HDD "
        "(default: merge into existing folders without overwriting HDD files), "
        "then optionally delete them on the SSD after confirmation."
    )
    parser.add_argument(
        "--ssd-disk",
        metavar="diskN",
        help="Whole-disk id for the SSD (skip auto-detect), e.g. disk4",
    )
    parser.add_argument(
        "--hdd-disk",
        metavar="diskN",
        help="Whole-disk id for the HDD (skip auto-detect), e.g. disk5",
    )
    parser.add_argument(
        "--dest-dir",
        metavar="PATH",
        help="Destination directory on the HDD (default: root of first data volume)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied; do not run rsync or delete",
    )
    parser.add_argument(
        "--pick-disks",
        action="store_true",
        help="Always show interactive menus to pick the SSD and HDD "
        "from detected external disks (even if only one candidate is found).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing files on the HDD when names match (default: merge only—"
        "skip files that already exist on the destination)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=None,
        metavar="N",
        help="Copy up to N top-level folders at the same time (separate rsync processes). "
        "Default: 2 when there are 2+ folders, else 1. Use 1 for one-folder-at-a-time (sequential). "
        "Higher values can improve throughput vs Finder when the SSD/USB/HDD can handle concurrent I/O.",
    )
    args = parser.parse_args()

    if shutil.which("rsync") is None:
        sys.exit("rsync not found. Install Command Line Tools or Xcode.")

    plist = _list_disks_plist()

    if args.ssd_disk:
        ssd_candidates: list[tuple[str, int, dict[str, Any]]] = []
    else:
        ssd_candidates = _find_external_candidates(plist, want_ssd=True, relaxed_solid=False)
        if not ssd_candidates:
            ssd_candidates = _find_external_candidates(plist, want_ssd=True, relaxed_solid=True)
            if ssd_candidates:
                print(
                    "Note: Using external disk(s) in the ~2 TB size range even though "
                    "diskutil reports SolidState=false (common for USB drive enclosures).\n",
                    file=sys.stderr,
                )
        if not ssd_candidates:
            print(
                "No external whole-disk SSD in the ~1.5–5.2 TiB capacity range "
                "(about 2 TB or 4 TB class drives).",
                file=sys.stderr,
            )
            _print_external_disk_diagnostic(plist, for_ssd=True)
            sys.exit(1)

    if args.hdd_disk:
        hdd_candidates: list[tuple[str, int, dict[str, Any]]] = []
    else:
        hdd_candidates = _find_external_candidates(plist, want_ssd=False, relaxed_solid=False)
        if not hdd_candidates:
            hdd_candidates = _find_external_candidates(plist, want_ssd=False, relaxed_solid=True)
            if hdd_candidates:
                print(
                    "Note: Using large external disk(s) as the destination even though "
                    "SolidState may be misreported by the enclosure.\n",
                    file=sys.stderr,
                )
        if not hdd_candidates:
            print(
                "No external whole-disk HDD over 15 TB (decimal).",
                file=sys.stderr,
            )
            _print_external_disk_diagnostic(plist, for_ssd=False)
            sys.exit(1)

    ssd_id, ssd_size, _ = _pick_one(
        "ssd-disk",
        ssd_candidates,
        args.ssd_disk,
        force_prompt=args.pick_disks,
    )
    hdd_id, hdd_size, _ = _pick_one(
        "hdd-disk",
        hdd_candidates,
        args.hdd_disk,
        force_prompt=args.pick_disks,
    )

    print()
    entered_ssd_id = input(f"Enter SSD ID [{ssd_id}]: ").strip() or ssd_id
    entered_hdd_id = input(f"Enter HDD ID [{hdd_id}]: ").strip() or hdd_id
    default_date = date.today().isoformat()
    transfer_date = input(f"Enter DATE (YYYY-MM-DD) [{default_date}]: ").strip() or default_date
    transfer_start_dt = datetime.now(IST)
    transfer_start_time = transfer_start_dt.isoformat()

    ssd_mounts = _mounts_for_whole_disk(plist, ssd_id)
    hdd_mounts = _mounts_for_whole_disk(plist, hdd_id)

    if not ssd_mounts:
        sys.exit(
            f"No mounted /Volumes data volume on SSD {ssd_id}. "
            "Mount the disk in Finder and run again."
        )
    if not hdd_mounts and not args.dest_dir:
        sys.exit(
            f"No mounted /Volumes data volume on HDD {hdd_id}. "
            "Mount the disk or set --dest-dir to an existing path."
        )

    ssd_root = Path(ssd_mounts[0])
    if len(ssd_mounts) > 1:
        print("SSD has multiple data volumes:")
        for i, m in enumerate(ssd_mounts, 1):
            print(f"  [{i}] {m}")
        choice = input("Enter number to use as source: ").strip()
        try:
            ssd_root = Path(ssd_mounts[int(choice) - 1])
        except (ValueError, IndexError):
            sys.exit("Invalid selection.")

    if args.dest_dir:
        dest_root = Path(args.dest_dir).expanduser()
    else:
        dest_root = Path(hdd_mounts[0])
        if len(hdd_mounts) > 1:
            print("HDD has multiple data volumes:")
            for i, m in enumerate(hdd_mounts, 1):
                print(f"  [{i}] {m}")
            choice = input("Enter number to use as destination root: ").strip()
            try:
                dest_root = Path(hdd_mounts[int(choice) - 1])
            except (ValueError, IndexError):
                sys.exit("Invalid selection.")

    folders = _top_level_folders(ssd_root)
    if not folders:
        sys.exit(f"No top-level folders to copy under {ssd_root}")

    # One du per top-level folder (progress/ETA is per folder, not whole volume)
    folder_du: list[tuple[Path, int]] = [(f, _du_bytes(f)) for f in folders]
    total_listed_bytes = sum(b for _, b in folder_du)

    print()
    print(f"SSD:  {ssd_id}  ({ssd_size / _TIB:.2f} TiB)  source: {ssd_root}")
    print(f"HDD:  {hdd_id}  ({hdd_size / _TIB:.2f} TiB)  dest:   {dest_root}")
    print("Folders to copy (sizes are per folder; progress bars are per folder):")
    for f, nbytes in folder_du:
        print(f"  - {f.name}  (~{_human_bytes(nbytes)})")
    print(f"\n  Total for these folders: ~{_human_bytes(total_listed_bytes)}")
    print(
        "  (Volume capacity is larger; other files at the volume root are not copied "
        "unless they sit inside these folders.)"
    )
    if args.overwrite:
        print("\nMode: overwrite — matching files on the HDD may be replaced.")
    else:
        print(
            "\nMode: merge — files that already exist on the HDD are left unchanged "
            "(only new paths are copied; nothing is deleted on the HDD)."
        )
    print()

    if args.dry_run:
        nw = args.parallel
        if nw is None:
            nw = 2 if len(folder_du) > 1 else 1
        nw = max(1, min(nw, len(folder_du)))
        print(
            f"Dry run: no copy performed. "
            f"({len(folder_du)} folder(s); a real run would use up to {nw} concurrent rsync.)\n"
        )
        try:
            _log_transfer_to_firestore(
                ssd_id=entered_ssd_id,
                hdd_id=entered_hdd_id,
                transfer_date=transfer_date,
                transfer_status="Success",
                start_time=transfer_start_time,
                end_time=datetime.now(IST).isoformat(),
                total_duration=_fmt_duration_hms((datetime.now(IST) - transfer_start_dt).total_seconds()),
                script_dir=Path(__file__).resolve().parent,
            )
            print("Firestore: transfer record saved to collection `HDD-transfer`.")
        except Exception as e:
            print(f"Firestore log failed: {e}", file=sys.stderr)
        return

    dest_root.mkdir(parents=True, exist_ok=True)

    n_workers = args.parallel
    if n_workers is None:
        n_workers = 2 if len(folder_du) > 1 else 1
    n_workers = max(1, min(n_workers, len(folder_du)))

    transferred: list[Path] = []

    def _run_one_folder(pair: tuple[Path, int], *, parallel: bool) -> Path:
        folder, approx_total = pair
        dst = dest_root / folder.name
        banner = f"\n--- rsync: {folder}  ->  {dst}\n"
        if approx_total > 0:
            banner += (
                f"(this folder only: ~{_human_bytes(approx_total)} — "
                "ETA from rsync or HDD growth estimate; merge skips may finish sooner)\n"
            )
        if parallel:
            with _PROGRESS_LOCK:
                print(banner, end="", flush=True)
        else:
            print(banner, end="", flush=True)
        cmd = _build_rsync_cmd(folder, dst, args.overwrite)
        _run_rsync_with_progress(
            cmd,
            label=folder.name,
            total_bytes=approx_total,
            dst=dst,
            parallel=parallel,
        )
        return folder

    transfer_status = "Fail"
    try:
        if n_workers <= 1:
            for pair in folder_du:
                transferred.append(_run_one_folder(pair, parallel=False))
        else:
            print(
                f"\n--- Parallel copy: up to {n_workers} rsync jobs at once "
                f"({len(folder_du)} folder(s); each job is a different destination folder) ---\n",
                flush=True,
            )

            def _parallel_worker(p: tuple[Path, int]) -> Path:
                return _run_one_folder(p, parallel=True)

            with ThreadPoolExecutor(max_workers=n_workers) as ex:
                futures = [ex.submit(_parallel_worker, pair) for pair in folder_du]
                for fut in as_completed(futures):
                    fut.result()
            transferred = [f for f, _ in folder_du]
    except subprocess.CalledProcessError as e:
        print(f"rsync failed with exit code {e.returncode}. Not deleting anything on SSD.", file=sys.stderr)
        try:
            _log_transfer_to_firestore(
                ssd_id=entered_ssd_id,
                hdd_id=entered_hdd_id,
                transfer_date=transfer_date,
                transfer_status=transfer_status,
                start_time=transfer_start_time,
                end_time=datetime.now(IST).isoformat(),
                total_duration=_fmt_duration_hms((datetime.now(IST) - transfer_start_dt).total_seconds()),
                script_dir=Path(__file__).resolve().parent,
            )
            print("Firestore: transfer record saved to collection `HDD-transfer`.")
        except Exception as log_err:
            print(f"Firestore log failed: {log_err}", file=sys.stderr)
        sys.exit(1)

    print("\nCopy finished successfully.")
    print(
        "\nThe following directories were copied from the SSD. "
        "To PERMANENTLY DELETE them from the SSD, press Enter.\n"
        "To cancel, press Ctrl+C or close the terminal.\n"
    )
    for p in transferred:
        print(f"  {p}")
    try:
        input("Press Enter to confirm deletion (or Ctrl+C to abort)... ")
    except KeyboardInterrupt:
        print("\nAborted. SSD files were not deleted.")
        try:
            _log_transfer_to_firestore(
                ssd_id=entered_ssd_id,
                hdd_id=entered_hdd_id,
                transfer_date=transfer_date,
                transfer_status=transfer_status,
                start_time=transfer_start_time,
                end_time=datetime.now(IST).isoformat(),
                total_duration=_fmt_duration_hms((datetime.now(IST) - transfer_start_dt).total_seconds()),
                script_dir=Path(__file__).resolve().parent,
            )
            print("Firestore: transfer record saved to collection `HDD-transfer`.")
        except Exception as log_err:
            print(f"Firestore log failed: {log_err}", file=sys.stderr)
        sys.exit(1)

    for p in transferred:
        if not str(p.resolve()).startswith(str(ssd_root.resolve()) + "/"):
            sys.exit(f"Refusing to delete outside SSD root: {p}")
        if p.name.startswith("."):
            print(f"Skipping hidden folder (not deleting): {p}")
            continue
        print(f"Removing {p} ...")
        shutil.rmtree(p)

    print("Done. Removed copied folders from the SSD.")
    transfer_status = "Success"
    try:
        _log_transfer_to_firestore(
            ssd_id=entered_ssd_id,
            hdd_id=entered_hdd_id,
            transfer_date=transfer_date,
            transfer_status=transfer_status,
            start_time=transfer_start_time,
            end_time=datetime.now(IST).isoformat(),
            total_duration=_fmt_duration_hms((datetime.now(IST) - transfer_start_dt).total_seconds()),
            script_dir=Path(__file__).resolve().parent,
        )
        print("Firestore: transfer record saved to collection `HDD-transfer`.")
    except Exception as e:
        print(f"Firestore log failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
