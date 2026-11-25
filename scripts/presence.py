# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy>=1.26", "opencv-python-headless>=4.9,<4.12"]
# ///
"""Phase 2 / Phase B — A-roll usability detection (parallel chunked keyframe scan).

Samples keyframes every 2 s at 640x360 via ffmpeg (no full 4K decode, no temp media),
detects person/face presence + sharpness + brightness, smooths over 5 samples,
keeps ranges >= 8 s, writes edit/aroll_usable.json and thumbnails in .cache/review/.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = REPO_ROOT / "edit" / "sources.json"
SYNC_PATH = REPO_ROOT / "edit" / "sync.json"
OUT_JSON = REPO_ROOT / "edit" / "aroll_usable.json"
REVIEW_DIR = REPO_ROOT / ".cache" / "review"
CACHE_8K = REPO_ROOT / ".cache" / "audio_8k"

W, H = 640, 360
FRAME_BYTES = W * H * 3
SAMPLE_STEP_SEC = 2.0
CHUNK_SEC = 480.0  # 8-minute chunks for parallel keyframe scanning
SMOOTH_WIN = 5
MIN_RANGE_SEC = 8.0
SHARPNESS_MIN = 35.0
BRIGHTNESS_MIN = 25.0
BRIGHTNESS_MAX = 235.0


def fmt_tc(sec: float) -> str:
    sec = max(0.0, sec)
    hh = int(sec // 3600)
    mm = int((sec % 3600) // 60)
    ss = sec % 60
    return f"{hh:02d}:{mm:02d}:{ss:05.2f}"


def load_zoom_rms_lookup(sources: list[dict], sync_files: dict) -> list[tuple[float, float, np.ndarray]]:
    """Load 8 kHz Zoom PCM arrays with their master start/end times for speech energy checks."""
    out = []
    for s in sources:
        if s["kind"] != "audio":
            continue
        f = CACHE_8K / (s["id"].replace("/", "__") + ".s16le")
        if not f.exists():
            continue
        pcm = np.fromfile(f, dtype="<i2").astype(np.float32) / 32768.0
        off = sync_files[s["id"]]["masterOffset"]
        out.append((off, off + len(pcm) / 8000.0, pcm))
    return out


def speech_rms(zoom_tracks: list[tuple[float, float, np.ndarray]], m0: float, m1: float) -> float:
    for off, end, pcm in zoom_tracks:
        lo = max(m0, off)
        hi = min(m1, end)
        if hi - lo >= 1.0:
            i0 = int(round((lo - off) * 8000))
            i1 = int(round((hi - off) * 8000))
            seg = pcm[i0:i1]
            if len(seg):
                return float(np.sqrt(np.mean(seg * seg)))
    return 0.0


def extract_thumbnail(video_path: Path, src_sec: float, out_jpg: Path) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{src_sec:.2f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=640:360",
        "-q:v",
        "3",
        str(out_jpg),
    ]
    subprocess.run(cmd, check=True)


def scan_chunk(args: tuple[str, str, float, float, float, float]) -> tuple[float, list[dict]]:
    """Worker: scan [chunk_start, chunk_start + chunk_dur) of video_path at 0.5 fps."""
    video_path_str, filename, chunk_start, chunk_dur, master_offset, rate = args
    haar_dir = Path(cv2.data.haarcascades)
    face_frontal = cv2.CascadeClassifier(str(haar_dir / "haarcascade_frontalface_default.xml"))
    face_profile = cv2.CascadeClassifier(str(haar_dir / "haarcascade_profileface.xml"))
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "2",
        "-skip_frame",
        "nokey",
        "-ss",
        f"{chunk_start:.2f}",
        "-t",
        f"{chunk_dur:.2f}",
        "-i",
        video_path_str,
        "-vf",
        f"fps=1/{int(SAMPLE_STEP_SEC)},scale={W}:{H}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=FRAME_BYTES * 4)
    assert proc.stdout is not None

    samples: list[dict] = []
    idx = 0
    while True:
        buf = proc.stdout.read(FRAME_BYTES)
        if len(buf) < FRAME_BYTES:
            break
        frame = np.frombuffer(buf, dtype=np.uint8).reshape((H, W, 3))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        bright = float(np.mean(gray))

        faces_f = face_frontal.detectMultiScale(
            gray, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28)
        )
        faces_p = (
            face_profile.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28)
            )
            if len(faces_f) == 0
            else ()
        )
        n_faces = len(faces_f) + len(faces_p)

        n_people = 0
        if n_faces == 0:
            small = cv2.resize(frame, (320, 180))
            rects, weights = hog.detectMultiScale(
                small, winStride=(8, 8), padding=(8, 8), scale=1.1
            )
            n_people = sum(1 for w in weights if float(w) > 0.6) if len(weights) else 0

        has_person = (n_faces > 0) or (n_people > 0)
        good_quality = (
            sharp >= SHARPNESS_MIN and BRIGHTNESS_MIN <= bright <= BRIGHTNESS_MAX
        )
        usable = has_person and good_quality

        src_t = chunk_start + idx * SAMPLE_STEP_SEC
        master_t = master_offset + src_t * rate
        samples.append(
            {
                "srcSec": round(src_t, 2),
                "masterSec": round(master_t, 2),
                "sharpness": sharp,
                "brightness": bright,
                "faces": n_faces,
                "people": n_people,
                "usable": usable,
            }
        )
        idx += 1

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {filename}@{chunk_start}s with code {proc.returncode}")
    return chunk_start, samples


def analyze_aroll_file_parallel(
    src: dict,
    master_offset: float,
    rate: float,
    max_workers: int,
) -> list[dict]:
    dur = float(src["duration"])
    tasks = []
    t = 0.0
    while t < dur:
        cdur = min(CHUNK_SEC, dur - t)
        if cdur >= SAMPLE_STEP_SEC:
            tasks.append((src["path"], src["filename"], t, cdur, master_offset, rate))
        t += CHUNK_SEC

    results: list[tuple[float, list[dict]]] = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(scan_chunk, task) for task in tasks]
        done_count = 0
        for fut in as_completed(futs):
            cs, seg = fut.result()
            results.append((cs, seg))
            done_count += 1
            print(
                f"    {src['filename']}: chunk {done_count}/{len(tasks)} done "
                f"(@{cs:.0f}s, {len(seg)} samples)",
                flush=True,
            )

    results.sort(key=lambda x: x[0])
    all_samples: list[dict] = []
    for _, seg in results:
        all_samples.extend(seg)
    print(f"  {src['filename']}: {len(all_samples)} total samples analyzed", flush=True)
    return all_samples


def smooth_and_group(samples: list[dict]) -> list[tuple[int, int]]:
    """Majority vote over SMOOTH_WIN samples, return (start_idx, end_idx_exclusive) runs >= MIN_RANGE_SEC."""
    n = len(samples)
    if n == 0:
        return []
    raw = np.array([1 if s["usable"] else 0 for s in samples], dtype=np.int32)
    half = SMOOTH_WIN // 2
    smoothed = np.zeros(n, dtype=np.int32)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        smoothed[i] = 1 if np.sum(raw[lo:hi]) > (hi - lo) / 2.0 else 0

    runs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if smoothed[i] == 1:
            j = i
            while j < n and smoothed[j] == 1:
                j += 1
            dur = (j - i) * SAMPLE_STEP_SEC
            if dur >= MIN_RANGE_SEC:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def main() -> int:
    sources_data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    sync_data = json.loads(SYNC_PATH.read_text(encoding="utf-8"))
    sources: list[dict] = sources_data["sources"]
    sync_files: dict = sync_data["files"]

    arolls = [s for s in sources if s["kind"] == "aroll"]
    zoom_tracks = load_zoom_rms_lookup(sources, sync_files)
    max_workers = min(8, max(2, (os.cpu_count() or 4) - 2))
    print(f"Using {max_workers} parallel workers for keyframe presence scan", flush=True)

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for old in REVIEW_DIR.glob("R*.jpg"):
        old.unlink()

    all_ranges: list[dict] = []
    stats_per_file: dict[str, dict] = {}

    for src in arolls:
        sid = src["id"]
        off = sync_files[sid]["masterOffset"]
        rate = sync_files[sid].get("rate", 1.0)
        print(f"=== Scanning {sid} (duration={src['duration']:.1f}s, offset={off:.2f}s) ===", flush=True)
        samples = analyze_aroll_file_parallel(src, off, rate, max_workers=max_workers)
        runs = smooth_and_group(samples)

        usable_count = sum(1 for s in samples if s["usable"])
        stats_per_file[sid] = {
            "totalSamples": len(samples),
            "usableSamples": usable_count,
            "usablePct": round(100.0 * usable_count / max(1, len(samples)), 1),
            "rangesFound": len(runs),
        }
        print(
            f"  -> {usable_count}/{len(samples)} usable samples "
            f"({stats_per_file[sid]['usablePct']}%), {len(runs)} ranges >= {MIN_RANGE_SEC:.0f}s",
            flush=True,
        )

        for i0, i1 in runs:
            seg = samples[i0:i1]
            src_start = seg[0]["srcSec"]
            src_end = min(src["duration"], seg[-1]["srcSec"] + SAMPLE_STEP_SEC)
            master_start = round(off + src_start * rate, 2)
            master_end = round(off + src_end * rate, 2)
            dur = round(master_end - master_start, 2)
            avg_sharp = round(float(np.mean([x["sharpness"] for x in seg])), 1)
            avg_bright = round(float(np.mean([x["brightness"] for x in seg])), 1)
            face_ratio = round(float(np.mean([1.0 if x["faces"] > 0 else 0.0 for x in seg])), 2)
            rms = round(speech_rms(zoom_tracks, master_start, master_end), 5)

            all_ranges.append(
                {
                    "arollId": sid,
                    "filename": src["filename"],
                    "videoPath": src["path"],
                    "srcStart": round(src_start, 2),
                    "srcEnd": round(src_end, 2),
                    "masterStart": master_start,
                    "masterEnd": master_end,
                    "duration": dur,
                    "avgSharpness": avg_sharp,
                    "avgBrightness": avg_bright,
                    "faceRatio": face_ratio,
                    "speechRms": rms,
                }
            )

    all_ranges.sort(key=lambda r: r["masterStart"])
    session_end = max(
        sync_files[s["id"]]["masterOffset"] + s["duration"]
        for s in sources
        if s["kind"] == "screen"
    )

    final_ranges: list[dict] = []
    for idx, r in enumerate(all_ranges, start=1):
        rid = f"R{idx:02d}"
        mid_src = 0.5 * (r["srcStart"] + r["srcEnd"])
        thumb_name = f"{rid}.jpg"
        extract_thumbnail(Path(r["videoPath"]), mid_src, REVIEW_DIR / thumb_name)

        is_early = r["masterStart"] < 600.0
        is_late = r["masterEnd"] > session_end - 300.0
        is_speaking = r["speechRms"] >= 0.0035
        if is_early and r["duration"] <= 60.0:
            suggested = "aroll"
            reason = f"Early intro segment ({r['duration']:.0f}s), clear face/person ({int(r['faceRatio']*100)}% face), sharpness {r['avgSharpness']}"
        elif is_late and r["duration"] <= 60.0:
            suggested = "aroll"
            reason = f"Closing/outro segment ({r['duration']:.0f}s), clear framing ({int(r['faceRatio']*100)}% face), sharpness {r['avgSharpness']}"
        elif r["faceRatio"] >= 0.6 and is_speaking:
            suggested = "screen+pip"
            reason = f"Presenter speaking in frame ({int(r['faceRatio']*100)}% face, sharp {r['avgSharpness']}); good PiP overlay"
        elif is_speaking:
            suggested = "screen+pip"
            reason = f"Presenter detected while speaking (person/face in frame, sharp {r['avgSharpness']}); verify not student"
        else:
            suggested = "screen+pip"
            reason = f"Quiet/pause segment with person in frame (low audio RMS={r['speechRms']:.4f}); check thumbnail"

        final_ranges.append(
            {
                "id": rid,
                "approved": False,
                "suggestedLayout": suggested,
                "reason": reason,
                "arollId": r["arollId"],
                "srcStart": r["srcStart"],
                "srcEnd": r["srcEnd"],
                "masterStart": r["masterStart"],
                "masterEnd": r["masterEnd"],
                "masterStartTC": fmt_tc(r["masterStart"]),
                "masterEndTC": fmt_tc(r["masterEnd"]),
                "duration": r["duration"],
                "avgSharpness": r["avgSharpness"],
                "avgBrightness": r["avgBrightness"],
                "faceRatio": r["faceRatio"],
                "speechRms": r["speechRms"],
                "thumbnail": f".cache/review/{thumb_name}",
            }
        )

    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "params": {
            "sampleStepSec": SAMPLE_STEP_SEC,
            "smoothWindow": SMOOTH_WIN,
            "minRangeSec": MIN_RANGE_SEC,
            "sharpnessMin": SHARPNESS_MIN,
        },
        "stats": stats_per_file,
        "rangeCount": len(final_ranges),
        "ranges": final_ranges,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    cards = []
    for r in final_ranges:
        cards.append(
            f"""
    <div class="card">
      <div class="hdr">
        <span class="badge">{r['id']}</span>
        <span class="layout">{r['suggestedLayout']}</span>
        <span class="dur">{r['duration']:.0f}s</span>
      </div>
      <img src="{Path(r['thumbnail']).name}" alt="{r['id']}" loading="lazy" />
      <div class="meta">
        <div><strong>Master:</strong> {r['masterStartTC']} – {r['masterEndTC']} ({r['masterStart']}s–{r['masterEnd']}s)</div>
        <div><strong>Source:</strong> {r['arollId']} @ {r['srcStart']:.0f}s–{r['srcEnd']:.0f}s</div>
        <div><strong>Metrics:</strong> face={int(r['faceRatio']*100)}% · sharp={r['avgSharpness']} · rms={r['speechRms']:.4f}</div>
        <div class="reason">{r['reason']}</div>
      </div>
    </div>"""
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Phase B — A-Roll Candidate Ranges (Session 1)</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
    h1 {{ margin: 0 0 8px; }}
    p.sub {{ color: #94a3b8; margin-top: 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}
    .card {{ background: #1e293b; border-radius: 10px; overflow: hidden; border: 1px solid #334155; }}
    .hdr {{ display: flex; gap: 8px; align-items: center; padding: 10px 12px; background: #0f172a; }}
    .badge {{ background: #3b82f6; color: #fff; font-weight: 700; padding: 2px 8px; border-radius: 6px; font-size: 0.85rem; }}
    .layout {{ background: #334155; color: #f8fafc; padding: 2px 8px; border-radius: 6px; font-size: 0.8rem; }}
    .dur {{ margin-left: auto; color: #94a3b8; font-size: 0.85rem; }}
    img {{ width: 100%; display: block; aspect-ratio: 16/9; object-fit: cover; background: #000; }}
    .meta {{ padding: 10px 12px; font-size: 0.82rem; line-height: 1.45; color: #cbd5e1; }}
    .reason {{ margin-top: 6px; color: #fbbf24; }}
  </style>
</head>
<body>
  <h1>Phase B — Candidate A-Roll Ranges ({len(final_ranges)} found)</h1>
  <p class="sub">Thumbnails captured at the midpoint of each candidate range. Approve or reject by ID (e.g., R01, R02…).</p>
  <div class="grid">{''.join(cards)}
  </div>
</body>
</html>
"""
    (REVIEW_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"\nWrote {len(final_ranges)} candidate ranges to {OUT_JSON.relative_to(REPO_ROOT)}")
    print(f"Wrote thumbnail gallery to {(REVIEW_DIR / 'index.html').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
