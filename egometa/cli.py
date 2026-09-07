"""CLI entrypoint. Only --parent-path is a flag; everything else is prompted."""
import argparse
import asyncio
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .checkpoint import Checkpoint
from .config import CITY_COORDS, ENVIRONMENTS, STATE_MAP, TAXONOMY
from .discover import discover_workers
from .pipeline import (RunOptions, load_qc, load_registration, process_worker)
from .util import geohash_encode, get_logger, prompt

log = get_logger()

AGE_BUCKETS = ["18-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54", "55-59", "60+"]
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="egometa", description="EgoCapture metadata generator")
    p.add_argument("--parent-path", type=Path, required=True,
                   help="Directory whose immediate subfolders are worker folders")
    return p.parse_args(argv)


def _interactive_config(parent_path: Path) -> RunOptions:
    print("\n=== EgoCapture Metadata Generator ===")
    print(f"Parent path: {parent_path}\n")

    company_name = prompt("Company / factory name")
    company_type = prompt("Company vertical", default="garment",
                         choices=sorted(TAXONOMY.keys()))
    environment_key = prompt("Environment preset", default="garment_factory",
                             choices=sorted(ENVIRONMENTS.keys()))
    city = prompt("City")
    state_default = STATE_MAP.get(city.strip().lower(), "")
    state = prompt("State/Province", default=state_default or "UNKNOWN - REQUIRED",
                   allow_empty=True)

    # Geohash — auto from city + optional per-factory precision, editable
    coords = CITY_COORDS.get(city.strip().lower())
    if coords:
        auto_gh = geohash_encode(coords[0], coords[1], precision=7)
        print(f"Auto-derived geohash for {city} + '{company_name}': {auto_gh}")
        geohash = prompt("Geohash (press Enter to accept auto)", default=auto_gh,
                         allow_empty=True)
    else:
        print(f"No coords known for '{city}' — geohash cannot be auto-derived.")
        geohash = prompt("Geohash (leave blank to mark UNKNOWN)", default="",
                         allow_empty=True) or None

    age_range = prompt("Operator age bucket", default="25-29", choices=AGE_BUCKETS)
    gender = prompt("Operator gender", default="Female", choices=GENDERS)

    backend = prompt("VLM backend", default="gemini", choices=["gemini", "claude"])
    frames_s = prompt("Frames per VLM call (1 call per 10 videos, cloned)", default="6")
    concurrency_s = prompt("Concurrency", default="6")
    output_dir_s = prompt("Output directory", default="./metadata_out")
    dry_run_s = prompt("Dry run (no API calls)?", default="n", choices=["y", "n"])

    reg_csv_s = prompt("Registration CSV path (optional)", default="", allow_empty=True)
    qc_csv_s = prompt("QC CSV path (optional)", default="", allow_empty=True)
    limit_s = prompt("Limit workers (blank = all)", default="", allow_empty=True)
    resume_s = prompt("Resume from previous checkpoint?", default="n", choices=["y", "n"])

    return RunOptions(
        parent_path=parent_path,
        company_name=company_name,
        company_type=company_type,
        environment_key=environment_key,
        city=city,
        state=state or None,
        output_dir=Path(output_dir_s),
        backend=backend,
        frames=int(frames_s),
        concurrency=int(concurrency_s),
        registration_csv=Path(reg_csv_s) if reg_csv_s else None,
        assume_demographics=False,
        geohash=geohash or None,
        qc_csv=Path(qc_csv_s) if qc_csv_s else None,
        dry_run=(dry_run_s == "y"),
        age_range=age_range,
        gender=gender,
    ), {"limit": int(limit_s) if limit_s else None, "resume": (resume_s == "y")}


async def _run(opt: RunOptions, limit: int, resume: bool) -> int:
    opt.output_dir.mkdir(parents=True, exist_ok=True)
    ckpt = Checkpoint(opt.output_dir / "checkpoint.sqlite")

    log.info("discovering workers under %s", opt.parent_path)
    workers = discover_workers(opt.parent_path, limit=limit)
    log.info("found %d worker folder(s)", len(workers))

    reg_map = load_registration(opt.registration_csv)
    qc_map = load_qc(opt.qc_csv)

    api_sem = asyncio.Semaphore(opt.concurrency)
    ffprobe_pool = ThreadPoolExecutor(max_workers=max(2, opt.concurrency))
    ffmpeg_pool = ThreadPoolExecutor(max_workers=max(2, opt.concurrency))

    total = len(workers)
    done = failed = skipped = frames_sent = missing_imu_ct = 0
    unknown_demo_count = 0
    per_worker_status = []

    async def _one(idx: int, wf) -> None:
        nonlocal done, failed, skipped, frames_sent, missing_imu_ct, unknown_demo_count
        if resume and ckpt.get_status(wf.key) in ("DONE", "DONE_NO_VLM", "DRY_RUN_OK"):
            log.info("[%s] skip (resume, already %s)", wf.key, ckpt.get_status(wf.key))
            skipped += 1
            per_worker_status.append({"worker": wf.key, "status": "RESUMED_SKIP"})
            return
        try:
            res = await process_worker(
                wf, idx + 1, opt, reg_map, qc_map,
                ffprobe_pool, ffmpeg_pool, api_sem,
            )
        except Exception as e:
            log.exception("[%s] unhandled error", wf.key)
            ckpt.mark(wf.key, "FAILED", str(e))
            failed += 1
            per_worker_status.append({"worker": wf.key, "status": "FAILED", "error": str(e)})
            return
        ckpt.mark(wf.key, res.status, res.error)
        per_worker_status.append({
            "worker": wf.key, "status": res.status, "error": res.error,
            "frames_sent": res.frames_sent, "missing_imu": res.missing_imu,
            "unknown_demographics": res.unknown_demographics,
            "videos_written": res.videos_written,
        })
        frames_sent += res.frames_sent
        if res.missing_imu:
            missing_imu_ct += 1
        unknown_demo_count += len(res.unknown_demographics)
        if res.status.startswith("DONE") or res.status == "DRY_RUN_OK":
            done += 1
        elif res.status == "SKIPPED":
            skipped += 1
        else:
            failed += 1

    tasks = [_one(i, wf) for i, wf in enumerate(workers)]
    await asyncio.gather(*tasks)

    ffprobe_pool.shutdown(wait=True)
    ffmpeg_pool.shutdown(wait=True)
    ckpt.close()

    report = {
        "generated_at_unix": int(time.time()),
        "parent_path": str(opt.parent_path),
        "company_name": opt.company_name,
        "company_type": opt.company_type,
        "backend": opt.backend,
        "dry_run": opt.dry_run,
        "workers_found": total,
        "workers_done": done,
        "workers_failed": failed,
        "workers_skipped": skipped,
        "total_frames_sent_to_api": frames_sent,
        "workers_missing_imu": missing_imu_ct,
        "unknown_required_demographic_fields": unknown_demo_count,
        "workers": per_worker_status,
    }
    (opt.output_dir / "run_report.json").write_text(json.dumps(report, indent=2))

    log.info("=" * 60)
    log.info("Summary: found=%d done=%d failed=%d skipped=%d", total, done, failed, skipped)
    log.info("Frames sent to API: %d | workers missing IMU: %d | unknown demo fields: %d",
             frames_sent, missing_imu_ct, unknown_demo_count)
    log.info("Report: %s", opt.output_dir / "run_report.json")
    return 0 if failed == 0 else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.parent_path.exists():
        print(f"error: --parent-path does not exist: {args.parent_path}", file=sys.stderr)
        return 2
    opt, run_kwargs = _interactive_config(args.parent_path)
    try:
        return asyncio.run(_run(opt, run_kwargs["limit"], run_kwargs["resume"]))
    except KeyboardInterrupt:
        log.error("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
