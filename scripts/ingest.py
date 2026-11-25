# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Phase 0 — Ingest: probe all source media with ffprobe and symlink into edit/assets/."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.json"
EDIT_DIR = REPO_ROOT / "edit"
ASSETS_DIR = EDIT_DIR / "assets"
SOURCES_PATH = EDIT_DIR / "sources.json"

OBS_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}-\d{2}-\d{2})\.")


def parse_fps(rate_str: str | None) -> float | None:
    if not rate_str or rate_str == "0/0":
        return None
    if "/" in rate_str:
        num, den = rate_str.split("/", 1)
        d = float(den)
        return round(float(num) / d, 4) if d else None
    return round(float(rate_str), 4)


def ffprobe_file(path: Path) -> dict:
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
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(fmt.get("duration", 0.0))
    size_bytes = int(fmt.get("size", path.stat().st_size))

    info: dict = {
        "duration": round(duration, 6),
        "sizeBytes": size_bytes,
    }
    if v_stream:
        info["video"] = {
            "codec": v_stream.get("codec_name"),
            "width": int(v_stream.get("width", 0)),
            "height": int(v_stream.get("height", 0)),
            "fps": parse_fps(v_stream.get("r_frame_rate"))
            or parse_fps(v_stream.get("avg_frame_rate")),
        }
        info["fps"] = info["video"]["fps"]
        info["size"] = [info["video"]["width"], info["video"]["height"]]
    else:
        info["fps"] = None
        info["size"] = None

    if a_stream:
        info["audio"] = {
            "codec": a_stream.get("codec_name"),
            "sampleRate": int(a_stream.get("sample_rate", 0)),
            "channels": int(a_stream.get("channels", 0)),
        }
    return info


def safe_asset_name(name: str) -> str:
    return name.replace(" ", "_")


def parse_obs_timestamp(filename: str) -> datetime | None:
    m = OBS_TS_RE.match(filename)
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H-%M-%S")


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    footage_root_str = os.environ.get("FOOTAGE_ROOT") or config["footageRoot"]
    footage_root = Path(os.path.expanduser(footage_root_str)).resolve()
    if not footage_root.is_dir():
        print(f"ERROR: Footage root does not exist: {footage_root}", file=sys.stderr)
        return 1

    ignore = set(config.get("ignore", []))
    folders: dict[str, str] = config["folders"]

    EDIT_DIR.mkdir(parents=True, exist_ok=True)
    for kind in folders:
        (ASSETS_DIR / kind).mkdir(parents=True, exist_ok=True)

    sources: list[dict] = []
    obs_t0: datetime | None = None

    for kind in ("screen", "aroll", "audio"):
        folder_name = folders[kind]
        src_dir = footage_root / folder_name
        if not src_dir.is_dir():
            print(f"ERROR: Source folder missing: {src_dir!r}", file=sys.stderr)
            return 1

        files = sorted(
            p
            for p in src_dir.iterdir()
            if p.is_file() and p.name not in ignore and not p.name.startswith(".")
        )

        for p in files:
            asset_name = safe_asset_name(p.name)
            rel_asset = f"assets/{kind}/{asset_name}"
            link_path = EDIT_DIR / rel_asset
            if link_path.is_symlink() or link_path.exists():
                link_path.unlink()
            link_path.symlink_to(p)

            probe = ffprobe_file(p)
            entry: dict = {
                "id": f"{kind}/{asset_name}",
                "kind": kind,
                "filename": p.name,
                "path": str(p),
                "assetPath": rel_asset,
                **probe,
            }

            if kind == "screen":
                dt = parse_obs_timestamp(p.name)
                if dt is not None:
                    if obs_t0 is None:
                        obs_t0 = dt
                    entry["wallClockStart"] = dt.isoformat()
                    entry["nominalStart"] = round((dt - obs_t0).total_seconds(), 3)

            sources.append(entry)
            print(
                f"  [{kind:6s}] {asset_name:32s}  {entry['duration']:8.2f}s"
                + (f"  nominal={entry['nominalStart']:8.1f}s" if "nominalStart" in entry else "")
            )

    payload = {
        "footageRoot": str(footage_root),
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sources": sources,
    }
    SOURCES_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {len(sources)} sources to {SOURCES_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
