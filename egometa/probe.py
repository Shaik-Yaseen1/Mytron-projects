"""ffprobe / ffmpeg wrappers."""
import io
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from .util import get_logger

log = get_logger()


@dataclass
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    codec: str
    duration_sec: float
    frame_count: int
    orientation: str  # Horizontal / Vertical
    ok: bool = True
    error: Optional[str] = None


def _which_or_raise(bin_name: str) -> str:
    p = shutil.which(bin_name)
    if not p:
        raise RuntimeError(f"{bin_name} not found on PATH. Install ffmpeg.")
    return p


def _parse_fps(rate: str) -> float:
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            n, d = float(num), float(den)
            return n / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def ffprobe_video(path: Path) -> VideoInfo:
    ffprobe = _which_or_raise("ffprobe")
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        data = json.loads(out.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return VideoInfo(path, 0, 0, 0.0, "", 0.0, 0, "Horizontal", ok=False, error=str(e))

    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        return VideoInfo(path, 0, 0, 0.0, "", 0.0, 0, "Horizontal", ok=False, error="no video stream")

    width = int(v.get("width") or 0)
    height = int(v.get("height") or 0)
    codec = v.get("codec_name", "")
    fps = _parse_fps(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0")
    duration = float(v.get("duration") or data.get("format", {}).get("duration") or 0.0)
    nb_frames_str = v.get("nb_frames") or v.get("nb_read_frames") or ""
    try:
        frame_count = int(nb_frames_str)
    except (TypeError, ValueError):
        frame_count = 0
    if frame_count <= 0 and fps > 0 and duration > 0:
        frame_count = int(round(duration * fps))
    orientation = "Horizontal" if width >= height else "Vertical"
    return VideoInfo(path, width, height, fps, codec, duration, frame_count, orientation, ok=True)


def extract_frame(video: Path, t_sec: float, max_side: int = 512, jpeg_q: int = 80) -> Optional[bytes]:
    ffmpeg = _which_or_raise("ffmpeg")
    cmd = [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-ss", f"{max(0.0, t_sec):.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("ffmpeg extract failed for %s @%.2fs: %s", video.name, t_sec, e)
        return None
    raw = out.stdout
    if not raw:
        return None
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = im.size
        m = max(w, h)
        if m > max_side:
            scale = max_side / m
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=jpeg_q, optimize=True)
        return buf.getvalue()
    except Exception as e:
        # Do NOT fall back to the raw/unresized frame here: on real footage that can be
        # several MB (vs. the ~30-100KB a properly resized JPEG produces), which is a
        # prime suspect for VLM call timeouts. Skip the frame instead.
        log.warning("PIL resize failed for %s @%.2fs (%d raw bytes), skipping frame: %s",
                    video.name, t_sec, len(raw), e)
        return None
