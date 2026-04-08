#!/usr/bin/env python3
"""
Simple external SD-card formatter (macOS), self-contained.
"""

from __future__ import annotations

import os
import plistlib
import re
import select
import subprocess
import sys
import time

POLL = 1.0
FILESYSTEM = "ExFAT"
VOLUME_NAME = "SDCARD"
PARTITION_SCHEME = "MBR"

WHOLE_DISK_RE = re.compile(r"^disk\d+$")

ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"
REDRAW = "\033[H\033[2J"
_USE_ALT = False

# Terminal width for table (fits default 80-col Terminal)
W = 78


def _color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _s(text: str, *codes: str) -> str:
    if not _color() or not codes:
        return text
    return "".join(codes) + text + "\033[0m"


def _run_diskutil(args: list[str]) -> bytes:
    r = subprocess.run(["diskutil", *args], capture_output=True, check=False)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"diskutil {' '.join(args)} failed ({r.returncode}): {err}")
    return r.stdout


def _plist(data: bytes) -> dict:
    return plistlib.loads(data)


def _whole_disks() -> list[str]:
    d = _plist(_run_diskutil(["list", "-plist"]))
    return sorted(x for x in (d.get("AllDisks") or []) if isinstance(x, str) and WHOLE_DISK_RE.match(x))


def _human_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    x = float(n)
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.1f} {u}" if u != "B" else f"{int(x)} {u}"
        x /= 1024.0
    return f"{n} B"


def _scan() -> list[dict]:
    out = []
    for did in _whole_disks():
        try:
            info = _plist(_run_diskutil(["info", "-plist", did]))
        except RuntimeError:
            continue
        if not info.get("WholeDisk"):
            continue
        if bool(info.get("Internal")) or bool(info.get("OSInternalMedia")):
            continue
        if not bool(info.get("RemovableMedia")):
            continue
        out.append(
            {
                "device": did,
                "name": str(info.get("MediaName") or info.get("IORegistryEntryName") or did),
                "size": int(info.get("IOKitSize") or info.get("Size") or 0),
                "kind": "removable",
            }
        )
    return sorted(out, key=lambda r: r["device"])


def _diskutil_text(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["diskutil", *args], capture_output=True, text=True, check=False)


def _erase_disk(device: str) -> None:
    _diskutil_text(["unmountDisk", "force", device])
    tries = [
        ["eraseDisk", FILESYSTEM, VOLUME_NAME, PARTITION_SCHEME, device],
        ["eraseDisk", FILESYSTEM, VOLUME_NAME, PARTITION_SCHEME, device],
        ["partitionDisk", device, "1", PARTITION_SCHEME, FILESYSTEM, VOLUME_NAME, "100%"],
        ["partitionDisk", device, "1", PARTITION_SCHEME, "MS-DOS FAT32", VOLUME_NAME, "100%"],
    ]
    waits = [0.6, 1.5, 0.4, 0.4]
    last_rc = 1
    for i, args in enumerate(tries):
        time.sleep(waits[i])
        p = _diskutil_text(args)
        if p.stdout:
            print(p.stdout, end="")
        if p.stderr:
            print(p.stderr, end="", file=sys.stderr)
        last_rc = p.returncode
        if p.returncode == 0:
            return
        _diskutil_text(["unmountDisk", "force", device])
    raise RuntimeError(f"Could not format {device}. Last diskutil exit: {last_rc}")


def _status_style(status: str) -> str:
    st = status.upper()
    if "LIVE" in st:
        return _s(status, "\033[36m")  # cyan
    if "LOCKED" in st:
        return _s(status, "\033[33m")  # yellow
    if "WAIT" in st:
        return _s(status, "\033[35m")  # magenta
    if "DONE" in st and "error" not in st.lower():
        return _s(status, "\033[32m")  # green
    if "error" in st.lower() or "FAIL" in st:
        return _s(status, "\033[31m")
    return _s(status, "\033[37m")


def _row_plain(text: str, inner_width: int) -> str:
    """inner_width = characters between the two vertical bars (excluding leading space)."""
    t = text
    if len(t) > inner_width:
        t = t[: max(0, inner_width - 1)] + "…"
    return " " + t + " " * max(0, inner_width - len(t))


def _render(cards: list[dict], *, status: str, phase: str) -> str:
    """
    phase: 'live' | 'locked' | 'wait' | 'done'
    """
    inner = W - 4  # space between │ … │
    top = "╭" + "─" * (W - 2) + "╮"
    bot = "╰" + "─" * (W - 2) + "╯"
    mid = "│"

    title_txt = "SD Card Formatter  ·  external removable only"
    if _color():
        line1 = mid + "  " + _s(title_txt, "\033[1m") + " " * max(0, inner - 2 - len(title_txt)) + mid
    else:
        line1 = mid + _row_plain(title_txt, inner) + mid

    stat_txt = "Status: " + status
    line2 = mid + _row_plain(stat_txt, inner) + mid

    sep = "├" + "─" * (W - 2) + "┤"

    hdr = f"{mid}  {'#':<3} {'Device':<16} {'Size':>10}  {'Type':<10}  {'Media name':<24} {mid}"
    rule = f"{mid}  {'─'*3} {'─'*16} {'─'*10}  {'─'*10}  {'─'*24} {mid}"

    body_lines: list[str] = []
    if not cards:
        msg = "( No SD card — insert into reader )"
        if _color():
            body_lines.append(
                mid + "  " + _s(msg, "\033[2m") + " " * max(0, inner - 2 - len(msg)) + mid
            )
        else:
            body_lines.append(mid + _row_plain(msg, inner) + mid)
    else:
        for i, c in enumerate(cards, start=1):
            dev = f"/dev/{c['device']}"
            sz = _human_size(c["size"])
            kind = c["kind"]
            name = c["name"]
            if len(name) > 24:
                name = name[:21] + "..."
            body_lines.append(
                f"{mid}  {i:<3} {dev:<16} {sz:>10}  {kind:<10}  {name:<24} {mid}"
            )

    foot: list[str] = []
    if phase == "live":
        foot = [
            mid + _row_plain("Updates ~1 s  ·  Plug in or unplug cards; the table refreshes.", inner) + mid,
            mid + _row_plain("[ Enter ]  Lock & format all rows     [ Ctrl+C ]  Quit", inner) + mid,
        ]
    elif phase == "locked":
        foot = [mid + _row_plain("Locked — formatting starts (output follows in the terminal).", inner) + mid]
    elif phase == "wait":
        foot = [mid + _row_plain("Unplug all devices shown above to continue.", inner) + mid]
    elif phase == "done":
        foot = [mid + _row_plain("Remove cards. Next cycle begins after all are unplugged.", inner) + mid]

    lines = [top, line1, line2, sep, hdr, rule]
    lines.extend(body_lines)
    lines.append(sep)
    lines.extend(foot)
    lines.append(bot)
    return "\n".join(lines)


def _draw(cards: list[dict], *, status: str, phase: str) -> None:
    txt = "\n" + _render(cards, status=status, phase=phase) + "\n"
    if _USE_ALT:
        sys.stdout.write(REDRAW + txt)
    else:
        sys.stdout.write(txt)
    sys.stdout.flush()


def _alt_on() -> None:
    global _USE_ALT
    if sys.stdout.isatty() and sys.stdin.isatty():
        sys.stdout.write(ALT_SCREEN_ON)
        sys.stdout.flush()
        _USE_ALT = True


def _alt_off() -> None:
    global _USE_ALT
    if _USE_ALT:
        sys.stdout.write(ALT_SCREEN_OFF)
        sys.stdout.flush()
        _USE_ALT = False


def _live_until_enter() -> list[dict]:
    while True:
        try:
            cards = _scan()
            _draw(
                cards,
                status="LIVE — table updates every 1 s",
                phase="live",
            )
            r, _, _ = select.select([sys.stdin], [], [], POLL)
            if r:
                sys.stdin.readline()
                return _scan()
        except KeyboardInterrupt:
            raise


def _wait_removed() -> None:
    while True:
        cards = _scan()
        if not cards:
            return
        _draw(
            cards,
            status="WAIT — remove SD card(s)",
            phase="wait",
        )
        time.sleep(POLL)


def main() -> int:
    _alt_on()
    try:
        while True:
            locked = _live_until_enter()
            if not locked:
                continue

            _draw(
                locked,
                status="LOCKED — erasing soon",
                phase="locked",
            )
            time.sleep(0.4)
            _alt_off()

            any_fail = False
            for i, c in enumerate(locked, start=1):
                print(f"\n── [{i}/{len(locked)}] /dev/{c['device']} — {c['name']}")
                try:
                    _erase_disk(c["device"])
                    print("   done\n")
                except RuntimeError as e:
                    any_fail = True
                    print(f"   error: {e}\n", file=sys.stderr)

            _alt_on()
            _draw(
                _scan(),
                status="DONE" if not any_fail else "DONE (some errors)",
                phase="done",
            )
            time.sleep(2.0)
            _wait_removed()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        _alt_off()


if __name__ == "__main__":
    raise SystemExit(main())
