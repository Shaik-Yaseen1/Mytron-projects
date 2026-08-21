"""Utilities: natural sort, slug, logging."""
import hashlib
import logging
import re
import sys


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "").strip().lower()).strip("_")
    return s or "unknown"


def stable_hash(s: str, length: int = 8) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:length]


def get_logger(name: str = "egometa", level: int = logging.INFO) -> logging.Logger:
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(level)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(h)
    return log


_GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_encode(lat: float, lon: float, precision: int = 7) -> str:
    """Standard geohash base32 encoder."""
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    bits, bit, ch, out = [], 0, 0, []
    even = True
    while len(out) < precision:
        if even:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                ch |= (1 << (4 - bit))
                lon_lo = mid
            else:
                lon_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                ch |= (1 << (4 - bit))
                lat_lo = mid
            else:
                lat_hi = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_GEOHASH_BASE32[ch])
            bit, ch = 0, 0
    return "".join(out)


def prompt(msg: str, default: str = "", choices: list = None, allow_empty: bool = False) -> str:
    """Interactive prompt with default + optional choice validation."""
    label = msg
    if choices:
        label += f" [{'/'.join(choices)}]"
    if default:
        label += f" (default: {default})"
    label += ": "
    while True:
        try:
            val = input(label).strip()
        except EOFError:
            val = ""
        if not val:
            val = default
        if not val and not allow_empty:
            print("  value required")
            continue
        if choices and val and val not in choices:
            print(f"  must be one of: {', '.join(choices)}")
            continue
        return val


def format_hms(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
