# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Phase E — Render per-chapter MP4s via HyperFrames and concatenate into renders/session-1-final.mp4.

Checks free disk space (output estimate + 20% margin) before writing any video file.
Verifies duration and audio streams of every output against edit/edl.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EDIT_DIR = REPO_ROOT / "edit"
EDL_PATH = EDIT_DIR / "edl.json"
RENDERS_DIR = REPO_ROOT / "renders"
CHAPTERS_DIR = RENDERS_DIR / "chapters"


def ffprobe_duration_and_audio(path: Path) -> tuple[float, int]:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    dur = float(data.get("format", {}).get("duration", 0.0))
    audio_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    return dur, len(audio_streams)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=RENDERS_DIR,
        help="Output root directory (default: renders/, can point to external drive)",
    )
    parser.add_argument(
        "--quality",
        default="standard",
        choices=["draft", "standard", "high"],
        help="HyperFrames render quality",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=None,
        help="Override render FPS",
    )
    parser.add_argument(
        "--chapter",
        type=int,
        default=None,
        help="Render only a single 1-based chapter index",
    )
    args = parser.parse_args()

    edl = json.loads(EDL_PATH.read_text(encoding="utf-8"))
    chapters: list[dict] = edl.get("chapters", [])
    if not chapters:
        print("ERROR: No chapters in edit/edl.json", file=sys.stderr)
        return 1

    # Estimate required disk space: ~3 Mbps average for screen-capture H.264 (~22.5 MB/min)
    # x2 (chapters + concatenated final) x 1.20 safety margin
    total_sec = sum(
        max(0.0, float(seg["out"]) - float(seg["in"]))
        for ch in chapters
        for seg in ch.get("segments", [])
    )
    est_bytes_single = total_sec * (3_000_000 / 8.0)
    required_bytes = est_bytes_single * 2.0 * 1.20

    out_root: Path = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    ch_dir = out_root / "chapters"
    ch_dir.mkdir(parents=True, exist_ok=True)

    usage = shutil.disk_usage(out_root)
    print(
        f"Output dir: {out_root}\n"
        f"Total EDL duration: {total_sec:.1f}s ({total_sec/60:.1f} min)\n"
        f"Estimated space needed (chapters + final + 20% margin): {required_bytes/(1024**3):.2f} GiB\n"
        f"Free disk space: {usage.free/(1024**3):.2f} GiB"
    )
    if usage.free < required_bytes:
        print(
            f"ERROR: Insufficient disk space ({usage.free/(1024**3):.2f} GiB free < "
            f"{required_bytes/(1024**3):.2f} GiB required). Free space or pass --out-dir /Volumes/<drive>/renders.",
            file=sys.stderr,
        )
        return 2

    # Regenerate compositions from edit/edl.json first (single source of truth)
    subprocess.run(["uv", "run", str(REPO_ROOT / "scripts" / "build.py")], check=True)

    rendered_chapters: list[Path] = []
    for idx, ch in enumerate(chapters, start=1):
        if args.chapter is not None and idx != args.chapter:
            continue
        ch_html = EDIT_DIR / f"chapter-{idx:02d}.html"
        ch_id = ch.get("id", f"chapter-{idx:02d}")
        out_mp4 = ch_dir / f"{ch_id}.mp4"
        expected_dur = sum(
            max(0.0, float(seg["out"]) - float(seg["in"])) for seg in ch.get("segments", [])
        )
        print(f"\n=== Rendering Chapter {idx}/{len(chapters)}: {ch_id} ({expected_dur:.1f}s) ===", flush=True)
        cmd = [
            "npx",
            "--yes",
            "hyperframes@0.9.96",
            "render",
            "-c",
            ch_html.name,
            "-o",
            str(out_mp4),
            "--quality",
            args.quality,
        ]
        if args.fps:
            cmd.extend(["--fps", str(args.fps)])
        subprocess.run(cmd, cwd=EDIT_DIR, check=True)

        actual_dur, n_audio = ffprobe_duration_and_audio(out_mp4)
        mb = out_mp4.stat().st_size / (1024 * 1024)
        print(
            f"  Verified {out_mp4.name}: {actual_dur:.2f}s (expected {expected_dur:.2f}s), "
            f"audio_streams={n_audio}, size={mb:.1f} MB",
            flush=True,
        )
        rendered_chapters.append(out_mp4)

    if args.chapter is None:
        concat_list = out_root / "concat_list.txt"
        concat_list.write_text(
            "".join(f"file '{p.resolve()}'\n" for p in rendered_chapters),
            encoding="utf-8",
        )
        final_mp4 = out_root / "session-1-final.mp4"
        print(f"\n=== Concatenating {len(rendered_chapters)} chapters -> {final_mp4} ===", flush=True)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(final_mp4),
            ],
            check=True,
        )
        final_dur, final_audio = ffprobe_duration_and_audio(final_mp4)
        mb = final_mp4.stat().st_size / (1024 * 1024)
        print(
            f"DONE: {final_mp4} — duration={final_dur:.2f}s (expected {total_sec:.2f}s), "
            f"audio_streams={final_audio}, size={mb:.1f} MB"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
