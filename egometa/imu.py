"""IMU parsing + motion-guided keyframe selection."""
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .util import get_logger

log = get_logger()


@dataclass
class ImuSample:
    t_us: int
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


@dataclass
class ImuSeries:
    samples: List[ImuSample]
    ok: bool
    rate_hz: float
    monotonic: bool
    error: str = ""


def parse_imu_files(paths: List[Path]) -> ImuSeries:
    samples: List[ImuSample] = []
    for p in paths:
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    try:
                        t_us = int(obj["t_us"])
                        acc = obj["acc"]
                        gyro = obj["gyro"]
                        samples.append(ImuSample(
                            t_us, float(acc[0]), float(acc[1]), float(acc[2]),
                            float(gyro[0]), float(gyro[1]), float(gyro[2]),
                        ))
                    except (KeyError, TypeError, ValueError, IndexError):
                        continue
        except OSError as e:
            log.warning("cannot read IMU file %s: %s", p, e)

    if not samples:
        return ImuSeries([], False, 0.0, False, error="no samples")

    samples.sort(key=lambda s: s.t_us)
    monotonic = all(samples[i].t_us <= samples[i + 1].t_us for i in range(len(samples) - 1))
    span_us = samples[-1].t_us - samples[0].t_us
    rate = (len(samples) / (span_us / 1e6)) if span_us > 0 else 0.0
    return ImuSeries(samples, True, rate, monotonic)


def motion_magnitudes(series: ImuSeries) -> List[Tuple[float, float]]:
    """Return list of (t_sec_relative, magnitude). g estimated as mean accel vector."""
    if not series.ok or not series.samples:
        return []
    n = len(series.samples)
    mean_ax = sum(s.ax for s in series.samples) / n
    mean_ay = sum(s.ay for s in series.samples) / n
    mean_az = sum(s.az for s in series.samples) / n
    t0 = series.samples[0].t_us
    out = []
    for s in series.samples:
        dax, day, daz = s.ax - mean_ax, s.ay - mean_ay, s.az - mean_az
        acc_dev = math.sqrt(dax * dax + day * day + daz * daz)
        gyro_mag = math.sqrt(s.gx * s.gx + s.gy * s.gy + s.gz * s.gz)
        out.append(((s.t_us - t0) / 1e6, acc_dev + gyro_mag))
    return out


def pick_peaks(mags: List[Tuple[float, float]], n: int, total_dur: float,
               min_sep_sec: float) -> List[float]:
    """Non-max suppression: sort by magnitude desc, take up to n with min separation."""
    if not mags or n <= 0:
        return []
    sorted_pts = sorted(mags, key=lambda x: -x[1])
    picked: List[float] = []
    for t, _m in sorted_pts:
        if t < 0 or t > total_dur:
            continue
        if all(abs(t - p) >= min_sep_sec for p in picked):
            picked.append(t)
            if len(picked) >= n:
                break
    picked.sort()
    return picked


def uniform_timestamps(total_dur: float, n: int) -> List[float]:
    if n <= 0 or total_dur <= 0:
        return []
    if n == 1:
        return [total_dur / 2.0]
    step = total_dur / (n + 1)
    return [step * (i + 1) for i in range(n)]
