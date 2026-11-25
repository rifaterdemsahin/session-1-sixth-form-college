# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Phase 5 — Audio polish: two-pass EBU R128 loudness normalization (-16 LUFS) + 80 Hz high-pass on Zoom H1n audio."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EDIT_DIR = REPO_ROOT / "edit"
SOURCES_PATH = EDIT_DIR / "sources.json"
OUT_DIR = EDIT_DIR / "assets" / "audio_norm"

LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def normalize_file(src_path: Path, dst_path: Path) -> dict:
    """Two-pass ffmpeg loudnorm to -16 LUFS with 80 Hz high-pass, saved as 256k AAC (.m4a) to save disk space."""
    # Pass 1: measure
    cmd1 = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(src_path),
        "-af",
        "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    res1 = subprocess.run(cmd1, capture_output=True, text=True, check=True)
    m = LOUDNORM_JSON_RE.search(res1.stderr)
    if not m:
        raise RuntimeError(f"Could not parse loudnorm pass-1 stats for {src_path.name}")
    stats = json.loads(m.group(0))

    # Pass 2: linear loudness normalization
    af = (
        f"highpass=f=80,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:"
        f"measured_I={stats['input_i']}:"
        f"measured_LRA={stats['input_lra']}:"
        f"measured_TP={stats['input_tp']}:"
        f"measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}"
    )
    tmp = dst_path.with_suffix(".tmp.m4a")
    cmd2 = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src_path),
        "-vn",
        "-af",
        af,
        "-ar",
        "48000",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        str(tmp),
    ]
    subprocess.run(cmd2, check=True)
    tmp.replace(dst_path)
    return stats


def main() -> int:
    usage = shutil.disk_usage(REPO_ROOT)
    free_gb = usage.free / (1024**3)
    print(f"Free disk space: {free_gb:.2f} GiB")
    if usage.free < 600 * 1024 * 1024:
        print("ERROR: Less than 600 MB free disk space for normalized audio!", file=sys.stderr)
        return 1

    sources_data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    audios = [s for s in sources_data["sources"] if s["kind"] == "audio"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for src in audios:
        src_path = Path(src["path"])
        dst_path = OUT_DIR / (Path(src["assetPath"]).stem + ".m4a")
        if dst_path.exists() and dst_path.stat().st_size > 0:
            print(f"Skipping {dst_path.name} (already exists)")
            continue
        print(f"=== Normalizing {src['filename']} -> {dst_path.name} (-16 LUFS, 80 Hz HPF) ===", flush=True)
        stats = normalize_file(src_path, dst_path)
        mb = dst_path.stat().st_size / (1024 * 1024)
        print(
            f"  Done: input_I={stats['input_i']} LUFS, TP={stats['input_tp']} dBTP -> "
            f"{dst_path.name} ({mb:.1f} MB)",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
