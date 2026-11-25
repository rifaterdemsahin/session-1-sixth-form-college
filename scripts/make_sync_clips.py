# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy>=1.26"]
# ///
"""Render 3 x 10s lip-sync verification clips (start, middle, end): ZV-1 picture + Zoom H1n audio."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = REPO_ROOT / "edit" / "sources.json"
SYNC_PATH = REPO_ROOT / "edit" / "sync.json"
CACHE_8K = REPO_ROOT / ".cache" / "audio_8k"
OUT_DIR = REPO_ROOT / "renders" / "sync_check"

AUDIO_SR = 8000
CLIP_DUR = 10.0


def find_loudest_window(
    audio_id: str,
    audio_offset: float,
    master_lo: float,
    master_hi: float,
) -> float:
    """Pick the 10 s window in [master_lo, master_hi - 10] with highest speech energy."""
    cache_file = CACHE_8K / (audio_id.replace("/", "__") + ".s16le")
    if not cache_file.exists():
        return (master_lo + master_hi - CLIP_DUR) / 2.0

    pcm = np.fromfile(cache_file, dtype="<i2").astype(np.float32) / 32768.0
    best_t = master_lo
    best_rms = -1.0
    step = 2.0
    t = master_lo
    while t + CLIP_DUR <= master_hi:
        a0 = int(round((t - audio_offset) * AUDIO_SR))
        a1 = int(round((t + CLIP_DUR - audio_offset) * AUDIO_SR))
        if 0 <= a0 and a1 <= len(pcm):
            seg = pcm[a0:a1]
            rms = float(np.sqrt(np.mean(seg * seg)))
            if rms > best_rms:
                best_rms = rms
                best_t = t
        t += step
    return round(best_t, 2)


def main() -> int:
    # Disk space check (require at least 200 MB free for 3 tiny 10s clips + 20% margin)
    usage = shutil.disk_usage(REPO_ROOT)
    free_gb = usage.free / (1024**3)
    print(f"Free disk space: {free_gb:.2f} GiB")
    if usage.free < 200 * 1024 * 1024:
        print("ERROR: Less than 200 MB free disk space!", file=sys.stderr)
        return 1

    sources_data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    sync_data = json.loads(SYNC_PATH.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in sources_data["sources"]}
    sync_files = sync_data["files"]

    arolls = [s for s in sources_data["sources"] if s["kind"] == "aroll"]
    audios = [s for s in sources_data["sources"] if s["kind"] == "audio"]

    # Compute overlapping (aroll, audio) intervals in master time
    overlaps: list[dict] = []
    for ar in arolls:
        ar_off = sync_files[ar["id"]]["masterOffset"]
        ar_rate = sync_files[ar["id"]].get("rate", 1.0)
        ar_start = ar_off
        ar_end = ar_off + ar["duration"] * ar_rate
        for au in audios:
            au_off = sync_files[au["id"]]["masterOffset"]
            au_start = au_off
            au_end = au_off + au["duration"]
            lo = max(ar_start, au_start)
            hi = min(ar_end, au_end)
            if hi - lo > 60.0:
                overlaps.append(
                    {
                        "aroll": ar,
                        "audio": au,
                        "ar_off": ar_off,
                        "ar_rate": ar_rate,
                        "au_off": au_off,
                        "lo": lo,
                        "hi": hi,
                    }
                )

    overlaps.sort(key=lambda x: x["lo"])
    if not overlaps:
        print("ERROR: No overlapping A-roll + Zoom audio intervals found!", file=sys.stderr)
        return 1

    # Choose 3 windows: start (first overlap, early), middle (middle of total span), end (last overlap, late)
    first_ov = overlaps[0]
    last_ov = overlaps[-1]

    # Start: between +60s and +420s into first overlap
    start_lo = first_ov["lo"] + 60.0
    start_hi = min(first_ov["hi"] - 30.0, first_ov["lo"] + 420.0)
    t_start = find_loudest_window(first_ov["audio"]["id"], first_ov["au_off"], start_lo, start_hi)

    # Middle: around 50% of total overlap span (preferring near end of C1201 or early C1202)
    mid_target = 0.5 * (first_ov["lo"] + last_ov["hi"])
    mid_ov = min(overlaps, key=lambda o: abs(0.5 * (o["lo"] + o["hi"]) - mid_target))
    mid_lo = max(mid_ov["lo"] + 60.0, mid_target - 300.0)
    mid_hi = min(mid_ov["hi"] - 60.0, mid_target + 300.0)
    if mid_hi - mid_lo < 20.0:
        mid_lo = mid_ov["lo"] + 0.4 * (mid_ov["hi"] - mid_ov["lo"])
        mid_hi = mid_ov["lo"] + 0.6 * (mid_ov["hi"] - mid_ov["lo"])
    t_mid = find_loudest_window(mid_ov["audio"]["id"], mid_ov["au_off"], mid_lo, mid_hi)

    # End: last 420s to 60s before end of last overlap
    end_lo = max(last_ov["lo"] + 30.0, last_ov["hi"] - 420.0)
    end_hi = last_ov["hi"] - 60.0
    t_end = find_loudest_window(last_ov["audio"]["id"], last_ov["au_off"], end_lo, end_hi)

    specs = [
        ("1_start", "Start", first_ov, t_start),
        ("2_middle", "Middle", mid_ov, t_mid),
        ("3_end", "End", last_ov, t_end),
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    for slug, label, ov, master_t in specs:
        ar = ov["aroll"]
        au = ov["audio"]
        ar_src_t = (master_t - ov["ar_off"]) / ov["ar_rate"]
        au_src_t = master_t - ov["au_off"]
        out_mp4 = OUT_DIR / f"sync_check_{slug}.mp4"

        vf = "scale=1280:720:flags=lanczos"
        if abs(ov["ar_rate"] - 1.0) > 1e-6:
            vf += f",setpts=PTS*{ov['ar_rate']:.8f}"

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{ar_src_t:.4f}",
            "-t",
            f"{CLIP_DUR:.3f}",
            "-i",
            ar["path"],
            "-ss",
            f"{au_src_t:.4f}",
            "-t",
            f"{CLIP_DUR:.3f}",
            "-i",
            au["path"],
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
        subprocess.run(cmd, check=True)
        size_mb = out_mp4.stat().st_size / (1024 * 1024)
        rec = {
            "label": label,
            "file": str(out_mp4.relative_to(REPO_ROOT)),
            "masterStartSec": master_t,
            "durationSec": CLIP_DUR,
            "arollId": ar["id"],
            "arollSrcSec": round(ar_src_t, 4),
            "audioId": au["id"],
            "audioSrcSec": round(au_src_t, 4),
            "sizeMB": round(size_mb, 2),
        }
        manifest.append(rec)
        print(
            f"  [{label:6s}] {out_mp4.name}  master={master_t:8.2f}s  "
            f"aroll={ar['filename']}@{ar_src_t:.2f}s  audio={au['filename']}@{au_src_t:.2f}s  "
            f"({size_mb:.2f} MB)"
        )

    # Write review HTML page so user can inspect all 3 clips in Google Chrome
    cards = []
    for r in manifest:
        mm, ss = divmod(r["masterStartSec"], 60)
        hh, mm = divmod(int(mm), 60)
        tc = f"{hh:02d}:{mm:02d}:{ss:05.2f}"
        cards.append(
            f"""
    <section class="card">
      <h2>{r['label']} — Master {tc} ({r['masterStartSec']}s)</h2>
      <p>Video: <code>{r['arollId']}</code> @ {r['arollSrcSec']}s | Audio: <code>{r['audioId']}</code> @ {r['audioSrcSec']}s (Zoom H1n only)</p>
      <video controls preload="metadata" src="{Path(r['file']).name}"></video>
    </section>"""
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Phase A — Lip-Sync Check Clips (Session 1)</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
    h1 {{ margin-top: 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 20px; }}
    .card {{ background: #1e293b; border-radius: 12px; padding: 16px; }}
    .card h2 {{ margin: 0 0 8px; font-size: 1.05rem; }}
    .card p {{ margin: 0 0 12px; font-size: 0.85rem; color: #94a3b8; }}
    video {{ width: 100%; border-radius: 8px; background: #000; }}
  </style>
</head>
<body>
  <h1>Phase A — Lip-Sync Verification (ZV-1 Picture + Zoom H1n Audio)</h1>
  <div class="grid">{''.join(cards)}
  </div>
</body>
</html>
"""
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote review page: {OUT_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
