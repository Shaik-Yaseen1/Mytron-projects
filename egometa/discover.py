"""Filesystem discovery: worker folders, mp4/aac/imu txt files."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .util import natural_key, get_logger

log = get_logger()


@dataclass
class VideoTriplet:
    """A video and its sibling audio + IMU files (matched by stem)."""
    stem: str
    video: Path
    audio: Optional[Path] = None
    imu: Optional[Path] = None


@dataclass
class WorkerFiles:
    key: str
    folder: Path
    videos: List[Path] = field(default_factory=list)
    audios: List[Path] = field(default_factory=list)
    imu_files: List[Path] = field(default_factory=list)
    triplets: List["VideoTriplet"] = field(default_factory=list)


def is_imu_txt(p: Path) -> bool:
    """Return True if the first non-empty line parses as JSON with t_us/acc/gyro."""
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    return False
                if not isinstance(obj, dict):
                    return False
                if "t_us" not in obj or "acc" not in obj or "gyro" not in obj:
                    return False
                acc, gyro = obj.get("acc"), obj.get("gyro")
                if not (isinstance(acc, list) and len(acc) == 3):
                    return False
                if not (isinstance(gyro, list) and len(gyro) == 3):
                    return False
                if not isinstance(obj["t_us"], int):
                    return False
                return True
            return False
    except OSError:
        return False


def discover_worker(folder: Path) -> WorkerFiles:
    wf = WorkerFiles(key=folder.name, folder=folder)
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf == ".mp4":
            wf.videos.append(p)
        elif suf == ".aac":
            wf.audios.append(p)
        elif suf == ".txt":
            if is_imu_txt(p):
                wf.imu_files.append(p)
    wf.videos.sort(key=lambda p: natural_key(p.name))
    wf.audios.sort(key=lambda p: natural_key(p.name))
    wf.imu_files.sort(key=lambda p: natural_key(p.name))

    audio_by_stem = {a.stem: a for a in wf.audios}
    imu_by_stem = {i.stem: i for i in wf.imu_files}
    wf.triplets = [
        VideoTriplet(
            stem=v.stem,
            video=v,
            audio=audio_by_stem.get(v.stem),
            imu=imu_by_stem.get(v.stem),
        )
        for v in wf.videos
    ]
    return wf


def discover_workers(parent: Path, limit: Optional[int] = None) -> List[WorkerFiles]:
    if not parent.is_dir():
        raise ValueError(f"parent-path is not a directory: {parent}")
    subs = sorted([p for p in parent.iterdir() if p.is_dir()], key=lambda p: natural_key(p.name))
    if limit:
        subs = subs[:limit]
    return [discover_worker(s) for s in subs]
