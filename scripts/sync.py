# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy>=1.26", "scipy>=1.12"]
# ///
"""Phase 1 — Sync: align OBS, Zoom H1n, and Sony ZV-1 via audio onset FFT cross-correlation."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import fftconvolve

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = REPO_ROOT / "edit" / "sources.json"
SYNC_PATH = REPO_ROOT / "edit" / "sync.json"
CACHE_DIR = REPO_ROOT / ".cache" / "audio_8k"

AUDIO_SR = 8000
ENV_SR = 1000
HOP = AUDIO_SR // ENV_SR  # 8 samples -> 1 kHz
MA_WIN = int(0.5 * ENV_SR)  # 0.5 s moving average
CONFIDENCE_THRESHOLD = 8.0


def extract_8k_pcm(src_path: Path, cache_file: Path) -> np.ndarray:
    """Extract mono 8 kHz s16le PCM via ffmpeg, cached on disk."""
    if not cache_file.exists() or cache_file.stat().st_size == 0:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(AUDIO_SR),
            "-f",
            "s16le",
            str(tmp),
        ]
        subprocess.run(cmd, check=True)
        tmp.replace(cache_file)
    raw = np.fromfile(cache_file, dtype="<i2")
    return raw.astype(np.float32) / 32768.0


def onset_envelope(samples: np.ndarray) -> np.ndarray:
    """Compute 1 kHz log-energy onset envelope with 0.5 s moving-average subtraction and z-norm."""
    n_frames = len(samples) // HOP
    if n_frames == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: n_frames * HOP].reshape(n_frames, HOP)
    env = np.mean(np.abs(frames), axis=1)
    log_env = np.log(env + 1e-6)
    hp = log_env - uniform_filter1d(log_env, size=MA_WIN, mode="nearest")
    std = float(np.std(hp))
    if std < 1e-8:
        return np.zeros_like(hp, dtype=np.float32)
    return ((hp - float(np.mean(hp))) / std).astype(np.float32)


def xcorr_full(canvas: np.ndarray, needle: np.ndarray) -> tuple[float, float]:
    """Full FFT cross-correlation of needle against canvas.

    Returns (offset_seconds, peak_z_score) where offset_seconds is the canvas time
    at which needle[0] aligns.
    """
    # fftconvolve(canvas, needle[::-1], mode='full') has index k corresponding to
    # lag = k - (len(needle) - 1) samples in canvas.
    corr = fftconvolve(canvas, needle[::-1], mode="full")
    peak_idx = int(np.argmax(corr))
    peak_val = float(corr[peak_idx])

    # Robust z-score excluding ±5 s around the peak
    mask = np.ones(len(corr), dtype=bool)
    lo = max(0, peak_idx - 5 * ENV_SR)
    hi = min(len(corr), peak_idx + 5 * ENV_SR)
    mask[lo:hi] = False
    bg = corr[mask] if np.any(mask) else corr
    bg_mean = float(np.mean(bg))
    bg_std = float(np.std(bg)) + 1e-8
    z = (peak_val - bg_mean) / bg_std

    # Sub-sample parabolic refinement
    if 0 < peak_idx < len(corr) - 1:
        y0, y1, y2 = float(corr[peak_idx - 1]), float(corr[peak_idx]), float(corr[peak_idx + 1])
        denom = y0 - 2.0 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
        delta = max(-0.5, min(0.5, delta))
    else:
        delta = 0.0

    lag_samples = (peak_idx + delta) - (len(needle) - 1)
    return lag_samples / ENV_SR, z


def xcorr_windowed(
    canvas: np.ndarray,
    needle: np.ndarray,
    approx_offset_sec: float,
    search_radius_sec: float,
) -> tuple[float, float]:
    """Correlate needle against canvas restricted to approx_offset_sec ± search_radius_sec."""
    n_len = len(needle)
    approx_idx = int(round(approx_offset_sec * ENV_SR))
    rad = int(round(search_radius_sec * ENV_SR))

    c_start = approx_idx - rad
    c_end = approx_idx + n_len + rad

    # Pad canvas slice if needed
    pad_left = max(0, -c_start)
    pad_right = max(0, c_end - len(canvas))
    slice_start = max(0, c_start)
    slice_end = min(len(canvas), c_end)
    if slice_start >= slice_end:
        return approx_offset_sec, 0.0

    sub = canvas[slice_start:slice_end]
    if pad_left > 0 or pad_right > 0:
        sub = np.pad(sub, (pad_left, pad_right), mode="constant")

    # mode='valid' gives corr[j] = sum(sub[j : j+n_len] * needle)
    # where j corresponds to canvas index c_start + j
    corr = fftconvolve(sub, needle[::-1], mode="valid")
    if len(corr) == 0:
        return approx_offset_sec, 0.0

    peak_idx = int(np.argmax(corr))
    peak_val = float(corr[peak_idx])

    # Background stats excluding ±0.5 s around peak
    mask = np.ones(len(corr), dtype=bool)
    lo = max(0, peak_idx - ENV_SR // 2)
    hi = min(len(corr), peak_idx + ENV_SR // 2)
    mask[lo:hi] = False
    bg = corr[mask] if np.any(mask) else corr
    z = (peak_val - float(np.mean(bg))) / (float(np.std(bg)) + 1e-8)

    if 0 < peak_idx < len(corr) - 1:
        y0, y1, y2 = float(corr[peak_idx - 1]), float(corr[peak_idx]), float(corr[peak_idx + 1])
        denom = y0 - 2.0 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
        delta = max(-0.5, min(0.5, delta))
    else:
        delta = 0.0

    lag_samples = c_start + peak_idx + delta
    return lag_samples / ENV_SR, z


def measure_drift(
    canvas: np.ndarray,
    needle: np.ndarray,
    global_offset_sec: float,
    canvas_origin_sec: float = 0.0,
    window_sec: float = 60.0,
    fractions: tuple[float, ...] = (0.08, 0.28, 0.50, 0.72, 0.90),
) -> dict:
    """Measure local sync offsets across the file to detect clock drift."""
    dur_sec = len(needle) / ENV_SR
    win_samples = int(window_sec * ENV_SR)
    points: list[dict] = []

    for frac in fractions:
        src_t = frac * dur_sec
        start_s = int(round(src_t * ENV_SR))
        end_s = min(len(needle), start_s + win_samples)
        if end_s - start_s < int(15 * ENV_SR):
            continue
        seg = needle[start_s:end_s]
        if float(np.std(seg)) < 1e-6:
            continue
        expected_canvas = global_offset_sec + (start_s / ENV_SR)
        found_canvas, z = xcorr_windowed(canvas, seg, expected_canvas, search_radius_sec=2.0)
        residual_ms = (found_canvas - expected_canvas) * 1000.0
        points.append(
            {
                "srcSec": round(start_s / ENV_SR, 2),
                "masterSec": round(found_canvas + canvas_origin_sec, 4),
                "residualMs": round(residual_ms, 2),
                "confidence": round(z, 2),
            }
        )

    good = [p for p in points if p["confidence"] >= 6.0]
    drift_ms_total = 0.0
    rate = 1.0
    if len(good) >= 2:
        xs = np.array([p["srcSec"] for p in good], dtype=np.float64)
        ys = np.array([p["residualMs"] / 1000.0 for p in good], dtype=np.float64)
        # Linear fit: residual_sec = slope * srcSec + intercept
        # Positive slope means master time advances faster than file time -> rate = 1 + slope
        slope, intercept = np.polyfit(xs, ys, 1)
        drift_ms_total = float(slope * dur_sec * 1000.0)
        # Only store rate correction if drift across the file exceeds 1 frame at 25 fps (40 ms)
        if abs(drift_ms_total) > 40.0:
            rate = round(1.0 + float(slope), 8)

    return {
        "points": points,
        "estimatedDriftMs": round(drift_ms_total, 2),
        "estimatedDriftFrames25": round(drift_ms_total / 40.0, 3),
        "rate": rate,
    }


def main() -> int:
    sources_data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    sources: list[dict] = sources_data["sources"]

    screen_files = [s for s in sources if s["kind"] == "screen"]
    audio_files = [s for s in sources if s["kind"] == "audio"]
    aroll_files = [s for s in sources if s["kind"] == "aroll"]

    print("=== Extracting 8 kHz mono audio & computing 1 kHz onset envelopes ===")
    envelopes: dict[str, np.ndarray] = {}
    rms_map: dict[str, float] = {}
    for s in sources:
        cache_name = s["id"].replace("/", "__") + ".s16le"
        pcm = extract_8k_pcm(Path(s["path"]), CACHE_DIR / cache_name)
        rms = float(np.sqrt(np.mean(pcm * pcm))) if len(pcm) else 0.0
        rms_map[s["id"]] = rms
        env = onset_envelope(pcm)
        envelopes[s["id"]] = env
        print(f"  {s['id']:40s}  len={len(env)/ENV_SR:8.2f}s  rms={rms:.5f}")

    # Step 1: Build OBS canvas from filename nominalStart times
    max_obs_end = max(s["nominalStart"] + s["duration"] for s in screen_files)
    obs_canvas = np.zeros(int(np.ceil(max_obs_end * ENV_SR)) + ENV_SR, dtype=np.float32)
    for s in screen_files:
        env = envelopes[s["id"]]
        start_idx = int(round(s["nominalStart"] * ENV_SR))
        end_idx = min(len(obs_canvas), start_idx + len(env))
        obs_canvas[start_idx:end_idx] = env[: end_idx - start_idx]

    print("\n=== Step 1: Align Zoom H1n files against OBS nominal canvas ===")
    zoom_offsets_raw: dict[str, tuple[float, float]] = {}
    for s in audio_files:
        off, z = xcorr_full(obs_canvas, envelopes[s["id"]])
        zoom_offsets_raw[s["id"]] = (off, z)
        flag = " [LOW CONF]" if z < CONFIDENCE_THRESHOLD else ""
        print(f"  {s['id']:40s}  offset={off:10.4f}s  z={z:6.2f}{flag}")

    # Build Zoom canvas (with padding to allow negative offsets if any)
    min_zoom = min(off for off, _ in zoom_offsets_raw.values())
    zoom_canvas_origin = min(0.0, min_zoom - 10.0)
    max_zoom_end = max(
        off + s["duration"] for s in audio_files for off, _ in [zoom_offsets_raw[s["id"]]]
    )
    zoom_canvas_len = int(np.ceil((max_zoom_end - zoom_canvas_origin + 10.0) * ENV_SR))
    zoom_canvas = np.zeros(zoom_canvas_len, dtype=np.float32)
    for s in audio_files:
        off, _ = zoom_offsets_raw[s["id"]]
        env = envelopes[s["id"]]
        start_idx = int(round((off - zoom_canvas_origin) * ENV_SR))
        end_idx = min(len(zoom_canvas), start_idx + len(env))
        if start_idx < 0:
            env = env[-start_idx:]
            start_idx = 0
        zoom_canvas[start_idx:end_idx] = env[: end_idx - start_idx]

    print("\n=== Step 2: Refine each OBS file start against Zoom canvas (±3 s window) ===")
    obs_refined: dict[str, tuple[float, float]] = {}
    for s in screen_files:
        approx_in_canvas = s["nominalStart"] - zoom_canvas_origin
        found_in_canvas, z = xcorr_windowed(
            zoom_canvas, envelopes[s["id"]], approx_in_canvas, search_radius_sec=3.0
        )
        found_master = found_in_canvas + zoom_canvas_origin
        obs_refined[s["id"]] = (found_master, z)
        diff = found_master - s["nominalStart"]
        flag = " [LOW CONF]" if z < CONFIDENCE_THRESHOLD else ""
        print(
            f"  {s['id']:40s}  nominal={s['nominalStart']:8.1f}s  "
            f"refined={found_master:10.4f}s  delta={diff:+7.3f}s  z={z:6.2f}{flag}"
        )

    # Anchor master timeline so OBS file 1 starts at exactly t = 0.0
    first_obs_id = screen_files[0]["id"]
    anchor_shift = obs_refined[first_obs_id][0]
    print(f"\nAnchoring master t=0 to {first_obs_id} (shift={-anchor_shift:+.4f}s)")

    # Rebuild Zoom canvas in anchored master time for ZV-1 correlation & drift checks
    anchored_zoom: dict[str, tuple[float, float]] = {
        sid: (off - anchor_shift, z) for sid, (off, z) in zoom_offsets_raw.items()
    }
    anchored_obs: dict[str, tuple[float, float]] = {
        sid: (off - anchor_shift, z) for sid, (off, z) in obs_refined.items()
    }

    min_az = min(off for off, _ in anchored_zoom.values())
    az_origin = min(0.0, min_az - 10.0)
    max_az_end = max(
        off + s["duration"] for s in audio_files for off, _ in [anchored_zoom[s["id"]]]
    )
    az_canvas = np.zeros(int(np.ceil((max_az_end - az_origin + 10.0) * ENV_SR)), dtype=np.float32)
    for s in audio_files:
        off, _ = anchored_zoom[s["id"]]
        env = envelopes[s["id"]]
        start_idx = int(round((off - az_origin) * ENV_SR))
        end_idx = min(len(az_canvas), start_idx + len(env))
        az_canvas[start_idx:end_idx] = env[: end_idx - start_idx]

    print("\n=== Step 3: Align Sony ZV-1 A-roll files against Zoom canvas (full search) ===")
    aroll_results: dict[str, dict] = {}
    for s in aroll_files:
        off_in_canvas, z = xcorr_full(az_canvas, envelopes[s["id"]])
        master_off = off_in_canvas + az_origin
        drift = measure_drift(az_canvas, envelopes[s["id"]], off_in_canvas, canvas_origin_sec=az_origin)
        aroll_results[s["id"]] = {
            "masterOffset": master_off,
            "confidence": z,
            "drift": drift,
        }
        flag = " [LOW CONF]" if z < CONFIDENCE_THRESHOLD else ""
        print(
            f"  {s['id']:40s}  offset={master_off:10.4f}s  z={z:6.2f}  "
            f"drift={drift['estimatedDriftMs']:+6.1f}ms ({drift['estimatedDriftFrames25']:+.2f}f@25) "
            f"rate={drift['rate']}{flag}"
        )
        for pt in drift["points"]:
            print(
                f"      src={pt['srcSec']:7.1f}s -> master={pt['masterSec']:8.3f}s  "
                f"residual={pt['residualMs']:+6.1f}ms  z={pt['confidence']:5.1f}"
            )

    # Assemble edit/sync.json
    files_out: dict[str, dict] = {}
    for s in sources:
        sid = s["id"]
        kind = s["kind"]
        if kind == "screen":
            off, z = anchored_obs[sid]
            entry = {
                "kind": kind,
                "masterOffset": round(off, 4),
                "masterOffsetMs": round(off * 1000.0, 1),
                "masterOffsetFrames30": round(off * 30.0, 2),
                "nominalStart": s["nominalStart"],
                "deltaFromNominalSec": round(off - s["nominalStart"], 4),
                "confidence": round(z, 2),
                "flagged": z < CONFIDENCE_THRESHOLD,
                "rate": 1.0,
            }
        elif kind == "audio":
            off, z = anchored_zoom[sid]
            entry = {
                "kind": kind,
                "masterOffset": round(off, 4),
                "masterOffsetMs": round(off * 1000.0, 1),
                "masterOffsetFrames25": round(off * 25.0, 2),
                "masterOffsetFrames30": round(off * 30.0, 2),
                "confidence": round(z, 2),
                "flagged": z < CONFIDENCE_THRESHOLD,
                "rate": 1.0,
            }
        else:
            res = aroll_results[sid]
            off = res["masterOffset"]
            z = res["confidence"]
            entry = {
                "kind": kind,
                "masterOffset": round(off, 4),
                "masterOffsetMs": round(off * 1000.0, 1),
                "masterOffsetFrames25": round(off * 25.0, 2),
                "masterOffsetFrames30": round(off * 30.0, 2),
                "confidence": round(z, 2),
                "flagged": z < CONFIDENCE_THRESHOLD,
                "rate": res["drift"]["rate"],
                "driftCheck": res["drift"],
            }
        files_out[sid] = entry

    flagged_list = [sid for sid, v in files_out.items() if v["flagged"]]
    payload = {
        "masterReference": first_obs_id,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "confidenceThreshold": CONFIDENCE_THRESHOLD,
        "flaggedCount": len(flagged_list),
        "flaggedFiles": flagged_list,
        "files": files_out,
    }
    SYNC_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote sync data to {SYNC_PATH.relative_to(REPO_ROOT)} (flagged={len(flagged_list)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
