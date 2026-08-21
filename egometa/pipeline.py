"""Per-worker orchestration with per-video metadata output."""
import asyncio
import csv
import json
import random
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__
from .backends import label_frames, resolved_model_id
from .config import (CAMERA_CONFIGURATION, CITY_COORDS, COORDINATE_SYSTEM,
                     DEMOGRAPHIC_PRIORS, DEVICE_CONSTANT, ENVIRONMENTS,
                     SENSORS_TEMPLATE, STATE_MAP, TAXONOMY)
from .discover import VideoTriplet, WorkerFiles
from .imu import motion_magnitudes, parse_imu_files, pick_peaks, uniform_timestamps
from .probe import VideoInfo, extract_frame, ffprobe_video
from .util import geohash_encode, get_logger, slug, stable_hash

log = get_logger()

VLM_BATCH_SIZE = 10


@dataclass
class RunOptions:
    parent_path: Path
    company_name: str
    company_type: str
    environment_key: str
    city: str
    state: Optional[str]
    output_dir: Path
    backend: str
    frames: int
    concurrency: int
    registration_csv: Optional[Path]
    assume_demographics: bool
    geohash: Optional[str]
    qc_csv: Optional[Path]
    dry_run: bool
    age_range: Optional[str] = None
    gender: Optional[str] = None


@dataclass
class WorkerResult:
    key: str
    status: str
    error: str = ""
    frames_sent: int = 0
    missing_imu: bool = False
    unknown_demographics: List[str] = field(default_factory=list)
    videos_written: int = 0


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2))


def _write_aggregate(doc: dict, out_dir: Path, worker_folder: Path, worker_key: str) -> None:
    central = out_dir / worker_key
    central.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, indent=2)
    (central / "metadata.json").write_text(payload)
    try:
        inline = worker_folder / "MetaData"
        inline.mkdir(parents=True, exist_ok=True)
        (inline / "metadata.json").write_text(payload)
    except OSError as e:
        log.warning("could not write inline MetaData/ for %s: %s", worker_key, e)


def _load_csv_map(path: Optional[Path], key_col: str) -> Dict[str, Dict[str, str]]:
    if not path:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            k = (row.get(key_col) or "").strip()
            if k:
                out[k] = {kk: (vv or "").strip() for kk, vv in row.items()}
    return out


def _resolve_state(city: str, state: Optional[str]) -> str:
    if state:
        return state
    return STATE_MAP.get(city.strip().lower(), "UNKNOWN - REQUIRED")


def _folder_ts_from_name(name: str) -> Optional[int]:
    m = re.search(r"(?<!\d)(\d{10})(?!\d)", name)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<!\d)(\d{13})(?!\d)", name)
    if m:
        return int(m.group(1)) // 1000
    return None


def _video_keyframes_for_vlm(
    v: VideoInfo, imu_path: Optional[Path], n_frames: int,
) -> Tuple[List[float], bool]:
    """Return list of local timestamps (sec) to sample from this single video."""
    if not v.ok or v.duration_sec <= 0 or n_frames <= 0:
        return [], False
    used_imu = False
    ts: List[float] = []
    if imu_path:
        series = parse_imu_files([imu_path])
        mags = motion_magnitudes(series)
        if mags and series.ok:
            min_sep = max(1.0, v.duration_sec / (n_frames * 2))
            ts = pick_peaks(mags, n_frames, v.duration_sec, min_sep)
            used_imu = len(ts) >= n_frames
    if not used_imu:
        ts = uniform_timestamps(v.duration_sec, n_frames)
    return ts, used_imu


def _union_clamp(vlm_items: List[str], candidates: List[str], min_n: int, max_n: int) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in vlm_items:
        k = item.strip().lower().replace(" ", "_")
        if k and k not in seen:
            seen.add(k)
            ordered.append(k)
    for c in candidates:
        k = c.strip().lower().replace(" ", "_")
        if k and k not in seen:
            seen.add(k)
            ordered.append(k)
        if len(ordered) >= max_n:
            break
    return ordered[:max_n] if len(ordered) >= min_n else ordered


def _union_cap(vlm_items: List[str], candidates: List[str], cap: int) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for src in (vlm_items, candidates):
        for item in src:
            k = item.strip().lower().replace(" ", "_")
            if k and k not in seen:
                seen.add(k)
                ordered.append(k)
            if len(ordered) >= cap:
                return ordered
    return ordered


def _resolve_demographics(
    opt: RunOptions, reg_row: Optional[Dict[str, str]],
    vlm_handedness: Optional[str],
) -> Tuple[str, str, str, str, str, str, List[str]]:
    age_range = "UNKNOWN - REQUIRED (5-year bucket)"
    gender = "UNKNOWN - REQUIRED"
    handedness = vlm_handedness or "Right-handed"
    prov_age = "unknown_required"
    prov_gender = "unknown_required"
    prov_hand = "vlm" if vlm_handedness else "default"
    if reg_row:
        if reg_row.get("age_range"):
            age_range = reg_row["age_range"]; prov_age = "registration"
        if reg_row.get("gender"):
            gender = reg_row["gender"]; prov_gender = "registration"
        if reg_row.get("handedness"):
            handedness = reg_row["handedness"]; prov_hand = "registration"
    elif opt.age_range or opt.gender:
        if opt.age_range:
            age_range = opt.age_range; prov_age = "user_input"
        if opt.gender:
            gender = opt.gender; prov_gender = "user_input"
    elif opt.assume_demographics:
        prior = DEMOGRAPHIC_PRIORS.get(opt.company_type, {})
        if prior.get("age_range"):
            age_range = prior["age_range"]; prov_age = "assumed"
        if prior.get("gender"):
            gender = prior["gender"]; prov_gender = "assumed"
    unknown = []
    if prov_age == "unknown_required":
        unknown.append("age_range")
    if prov_gender == "unknown_required":
        unknown.append("gender")
    return age_range, gender, handedness, prov_age, prov_gender, prov_hand, unknown


def _resolve_location(opt: RunOptions) -> Tuple[str, str]:
    if opt.geohash:
        return opt.geohash, "user_input"
    coords = CITY_COORDS.get(opt.city.strip().lower())
    if coords:
        return geohash_encode(coords[0], coords[1], precision=7), "derived_from_city"
    return "UNKNOWN - REQUIRED (geo-hash)", "unknown_required"


def _measure_imu_rate(imu_path: Optional[Path]) -> Optional[float]:
    if not imu_path:
        return None
    series = parse_imu_files([imu_path])
    if not series.ok or series.rate_hz <= 0:
        return None
    return series.rate_hz


def _build_camera_config(v: VideoInfo, video_filename: str) -> List[dict]:
    cams = []
    for tmpl in CAMERA_CONFIGURATION:
        cam = json.loads(json.dumps(tmpl))  # deep copy
        if cam.get("sensor_type") == "rgb":
            cam["stream_file"] = video_filename
            if v.ok:
                cam["resolution"] = {"width": v.width, "height": v.height}
                cam["frame_rate"] = int(round(v.fps)) if v.fps else cam.get("frame_rate", 30)
        cams.append(cam)
    return cams


def _build_video_metadata(
    triplet: VideoTriplet,
    v: VideoInfo,
    vlm: Optional[Dict],
    worker_ctx: dict,
    opt: RunOptions,
    prev_end_ts: Optional[int],
) -> Tuple[dict, int, List[str]]:
    tax = TAXONOMY[opt.company_type]
    env = ENVIRONMENTS[opt.environment_key]
    state = _resolve_state(opt.city, opt.state)

    try:
        start_ts = int(v.path.stat().st_mtime)
    except OSError:
        start_ts = worker_ctx["worker_start_ts"]
    duration = float(v.duration_sec if v.ok else 0.0)
    end_ts = start_ts + int(round(duration))
    gap = 0.0 if prev_end_ts is None else max(0.0, start_ts - prev_end_ts)

    difficulty = vlm["task_difficulty"] if vlm else tax["default_difficulty"]
    vlm_handedness = vlm["handedness"] if vlm else ""

    (age_range, gender, handedness, _pa, _pg, _ph,
     unknown_demo) = _resolve_demographics(opt, worker_ctx.get("reg_row"), vlm_handedness or None)

    location_val, _ = _resolve_location(opt)
    env_id = f"{slug(env['l3'])}_{slug(opt.city)}_{worker_ctx['op_id_num']:04d}"

    sensors = json.loads(json.dumps(SENSORS_TEMPLATE))  # deep copy
    rate = _measure_imu_rate(triplet.imu)
    if rate:
        sensors["imu"]["sampling_rate_hz"] = int(round(rate))

    cameras = _build_camera_config(v, triplet.video.name)
    device_id = f"{DEVICE_CONSTANT['device_id_prefix']}{stable_hash(worker_ctx['worker_key'] + '/' + triplet.stem)}"

    doc = {
        "episode-uuid": str(uuid.uuid4()),
        "session_id": worker_ctx["session_id"],
        "operator-id": worker_ctx["operator_id"],
        "operator_consent": "Yes",
        "operator_job": tax["operator_job"],
        "start_time_unix": int(start_ts),
        "end_time_unix": int(end_ts),
        "duration_seconds": round(duration, 3),
        "gap_seconds": round(gap, 3),
        "task-id": tax["task_id"],
        "task_description": tax["task_description"],
        "skill_group": tax["skill_group"],
        "task_difficulty": difficulty,
        "environment-id": env_id,
        "environment_l1": env["l1"],
        "environment_l2": env["l2"],
        "environment_l3": env["l3"],
        "city": opt.city,
        "state_province": state,
        "country": "India",
        "location_geohash": location_val,
        "device_type": DEVICE_CONSTANT["device_type"],
        "device_kit_id": DEVICE_CONSTANT["device_kit_id"],
        "device_id": device_id,
        "device_generation": DEVICE_CONSTANT["device_generation"],
        "firmware_version": DEVICE_CONSTANT["firmware_version"],
        "age_range": age_range,
        "gender": gender,
        "handedness": handedness,
        "coordinate_system": dict(COORDINATE_SYSTEM),
        "camera_configuration": cameras,
        "sensors": sensors,
    }
    return doc, end_ts, unknown_demo


def _build_aggregate(
    wf: WorkerFiles,
    vinfos: List[VideoInfo],
    worker_ctx: dict,
    opt: RunOptions,
    total_frames_sent: int,
    any_imu_used: bool,
) -> dict:
    """Worker-level summary (keeps existing central catalog useful)."""
    tax = TAXONOMY[opt.company_type]
    env = ENVIRONMENTS[opt.environment_key]
    state = _resolve_state(opt.city, opt.state)
    total_dur = sum(v.duration_sec for v in vinfos if v.ok)
    start_ts = worker_ctx["worker_start_ts"]
    end_ts = start_ts + int(round(total_dur))
    location_val, _ = _resolve_location(opt)
    env_id = f"{slug(env['l3'])}_{slug(opt.city)}_{worker_ctx['op_id_num']:04d}"

    chunks = []
    for v in vinfos:
        if not v.ok:
            continue
        chunks.append({
            "video_id_file_name": v.path.name,
            "metadata_file": v.path.with_suffix(".json").name,
            "duration_sec": round(v.duration_sec, 3),
            "frame_count": v.frame_count,
        })

    return {
        "session_id": worker_ctx["session_id"],
        "operator-id": worker_ctx["operator_id"],
        "operator_job": tax["operator_job"],
        "worker_folder": wf.key,
        "city": opt.city,
        "state_province": state,
        "country": "India",
        "location_geohash": location_val,
        "environment_id": env_id,
        "environment_l1": env["l1"],
        "environment_l2": env["l2"],
        "environment_l3": env["l3"],
        "task-id": tax["task_id"],
        "task_description": tax["task_description"],
        "skill_group": tax["skill_group"],
        "device_kit_id": DEVICE_CONSTANT["device_kit_id"],
        "device_generation": DEVICE_CONSTANT["device_generation"],
        "start_time_unix": int(start_ts),
        "end_time_unix": int(end_ts),
        "total_duration_sec": round(total_dur, 3),
        "video_count": len(chunks),
        "videos": chunks,
        "_generator": {
            "tool_version": __version__,
            "backend": opt.backend,
            "model": resolved_model_id(opt.backend),
            "total_frames_sent": total_frames_sent,
            "vlm_batch_size": VLM_BATCH_SIZE,
            "generated_at_unix": int(time.time()),
            "imu_guided_frames": any_imu_used,
        },
    }


async def _run_vlm(
    frames_bytes: List[bytes], opt: RunOptions, api_semaphore: asyncio.Semaphore,
) -> Optional[Dict]:
    if not frames_bytes:
        return None
    tax = TAXONOMY[opt.company_type]
    ctx = {
        "company_type": opt.company_type,
        "task_description": tax["task_description"],
        "action_candidates": tax["action_candidates"],
        "object_candidates": tax["object_candidates"],
        "subtask_candidates": tax["subtask_candidates"],
        "indoor_outdoor": tax["indoor_outdoor"],
        "default_difficulty": tax["default_difficulty"],
    }
    try:
        async with api_semaphore:
            return await label_frames(frames_bytes, ctx, opt.backend)
    except Exception as e:
        log.error("VLM call failed: %s", e)
        return None


async def process_worker(
    wf: WorkerFiles,
    op_index: int,
    opt: RunOptions,
    reg_map: Dict[str, Dict[str, str]],
    qc_map: Dict[str, Dict[str, str]],
    ffprobe_pool: ThreadPoolExecutor,
    ffmpeg_pool: ThreadPoolExecutor,
    api_semaphore: asyncio.Semaphore,
) -> WorkerResult:
    log.info("[%s] start (videos=%d, imu=%d, audio=%d)",
             wf.key, len(wf.videos), len(wf.imu_files), len(wf.audios))

    if not wf.triplets:
        return WorkerResult(wf.key, "SKIPPED", error="no mp4 files")

    loop = asyncio.get_running_loop()
    triplets = wf.triplets  # already sorted by video name
    vinfos = await asyncio.gather(*[
        loop.run_in_executor(ffprobe_pool, ffprobe_video, t.video) for t in triplets
    ])
    ok_pairs = [(t, v) for t, v in zip(triplets, vinfos) if v.ok]
    if not ok_pairs:
        return WorkerResult(wf.key, "FAILED", error="all videos failed to probe")

    # Worker-level identifiers (shared across all videos)
    worker_start_ts = _folder_ts_from_name(wf.folder.name)
    if worker_start_ts is None:
        mtimes = [int(v.path.stat().st_mtime) for v in vinfos if v.ok and v.path.exists()]
        worker_start_ts = min(mtimes) if mtimes else int(time.time())
    session_id = str(uuid.uuid4())
    op_id_num = random.randint(1000, 9999)
    operator_id = f"{op_id_num:04d}"
    reg_row = reg_map.get(wf.key)
    qc_row = qc_map.get(wf.key)

    worker_ctx = {
        "worker_key": wf.key,
        "worker_start_ts": worker_start_ts,
        "session_id": session_id,
        "operator_id": operator_id,
        "op_id_num": op_id_num,
        "reg_row": reg_row,
        "qc_row": qc_row,
    }

    total_frames_sent = 0
    any_imu_used = False
    unknown_demo: List[str] = []
    videos_written = 0
    prev_end_ts: Optional[int] = None
    got_any_vlm = False

    # Process in batches of VLM_BATCH_SIZE, one VLM call per batch (on first video)
    for batch_start in range(0, len(ok_pairs), VLM_BATCH_SIZE):
        batch = ok_pairs[batch_start:batch_start + VLM_BATCH_SIZE]
        head_triplet, head_v = batch[0]
        head_ts, head_imu_used = _video_keyframes_for_vlm(head_v, head_triplet.imu, opt.frames)
        any_imu_used = any_imu_used or head_imu_used

        vlm: Optional[Dict] = None
        frames_bytes: List[bytes] = []
        if not opt.dry_run and head_ts:
            for t in head_ts:
                b = await loop.run_in_executor(ffmpeg_pool, extract_frame, head_triplet.video, t)
                if b:
                    frames_bytes.append(b)
            vlm = await _run_vlm(frames_bytes, opt, api_semaphore)
            total_frames_sent += len(frames_bytes)
            if vlm:
                got_any_vlm = True

        for triplet, v in batch:
            doc, end_ts, unknown = _build_video_metadata(
                triplet, v, vlm, worker_ctx, opt, prev_end_ts,
            )
            _write_json(triplet.video.with_suffix(".json"), doc)
            videos_written += 1
            prev_end_ts = end_ts
            for u in unknown:
                if u not in unknown_demo:
                    unknown_demo.append(u)

    # Worker-level aggregate
    aggregate = _build_aggregate(wf, vinfos, worker_ctx, opt, total_frames_sent, any_imu_used)
    _write_aggregate(aggregate, opt.output_dir, wf.folder, wf.key)

    if opt.dry_run:
        status = "DRY_RUN_OK"
    else:
        status = "DONE" if got_any_vlm else "DONE_NO_VLM"
    return WorkerResult(
        wf.key, status,
        frames_sent=total_frames_sent,
        missing_imu=not wf.imu_files,
        unknown_demographics=unknown_demo,
        videos_written=videos_written,
    )


def load_registration(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    return _load_csv_map(path, "worker_folder")


def load_qc(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    return _load_csv_map(path, "worker_folder")
