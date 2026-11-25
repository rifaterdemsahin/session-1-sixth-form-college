# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Phase 4 — Build HyperFrames compositions (edit/index.html + edit/chapter-NN.html) from edit/edl.json."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EDIT_DIR = REPO_ROOT / "edit"
SOURCES_PATH = EDIT_DIR / "sources.json"
SYNC_PATH = EDIT_DIR / "sync.json"
EDL_PATH = EDIT_DIR / "edl.json"

FADE_SEC = 0.3


def build_source_intervals(sources: list[dict], sync_files: dict) -> dict[str, list[dict]]:
    """Group sources by kind with their master [start, end) intervals."""
    by_kind: dict[str, list[dict]] = {"screen": [], "aroll": [], "audio": []}
    for s in sources:
        kind = s["kind"]
        sf = sync_files[s["id"]]
        off = float(sf["masterOffset"])
        rate = float(sf.get("rate", 1.0))
        dur = float(s["duration"])
        asset_path = s["assetPath"]
        # Use loudness-normalized audio if Phase 5 generated it
        if kind == "audio":
            norm_m4a = f"assets/audio_norm/{Path(asset_path).stem}.m4a"
            norm_wav = f"assets/audio_norm/{Path(asset_path).name}"
            if (EDIT_DIR / norm_m4a).exists():
                asset_path = norm_m4a
            elif (EDIT_DIR / norm_wav).exists():
                asset_path = norm_wav
        by_kind[kind].append(
            {
                "id": s["id"],
                "assetPath": asset_path,
                "masterStart": off,
                "masterEnd": off + dur * rate,
                "masterOffset": off,
                "rate": rate,
                "duration": dur,
            }
        )
    for kind in by_kind:
        by_kind[kind].sort(key=lambda x: x["masterStart"])
    return by_kind


def cover_range(
    intervals: list[dict],
    m_in: float,
    m_out: float,
    out_start: float,
) -> list[dict]:
    """Find covering source clips for master [m_in, m_out), splitting at file boundaries."""
    clips: list[dict] = []
    cursor = m_in
    for iv in intervals:
        if iv["masterEnd"] <= cursor:
            continue
        if iv["masterStart"] >= m_out:
            break
        seg_start = max(cursor, iv["masterStart"])
        seg_end = min(m_out, iv["masterEnd"])
        if seg_end - seg_start <= 0.01:
            continue
        dur = seg_end - seg_start
        src_t = (seg_start - iv["masterOffset"]) / iv["rate"]
        clip_out_start = out_start + (seg_start - m_in)
        clips.append(
            {
                "id": iv["id"],
                "assetPath": iv["assetPath"],
                "outStart": round(clip_out_start, 4),
                "duration": round(dur, 4),
                "mediaStart": round(max(0.0, src_t), 4),
            }
        )
        cursor = seg_end
        if cursor >= m_out - 0.01:
            break
    return clips


def render_composition_html(
    title: str,
    width: int,
    height: int,
    fps: int,
    chapters: list[dict],
    by_kind: dict[str, list[dict]],
    include_chapter_cards: bool = True,
) -> tuple[str, float]:
    """Generate a HyperFrames HTML composition for the given chapters."""
    video_tags: list[str] = []
    audio_tags: list[str] = []
    chapter_cards: list[dict] = []

    out_cursor = 0.0
    for ch_idx, ch in enumerate(chapters):
        ch_start = out_cursor
        ch_title = ch.get("title", ch.get("id", f"Chapter {ch_idx + 1}"))
        ch_id = ch.get("id", f"{ch_idx + 1:02d}")
        if include_chapter_cards:
            chapter_cards.append(
                {
                    "id": f"card-{ch_idx}",
                    "label": f"Chapter {ch_idx + 1}",
                    "title": ch_title,
                    "start": round(ch_start, 3),
                }
            )

        for seg in ch.get("segments", []):
            m_in = float(seg["in"])
            m_out = float(seg["out"])
            if m_out <= m_in:
                continue
            seg_dur = m_out - m_in
            layout = seg.get("layout", "screen")

            # Layer 0: OBS screen capture (always present for screen and screen+pip)
            if layout in ("screen", "screen+pip"):
                for c in cover_range(by_kind["screen"], m_in, m_out, out_cursor):
                    video_tags.append(
                        f'      <video class="clip screen" src="{html.escape(c["assetPath"])}" muted playsinline preload="auto" '
                        f'data-start="{c["outStart"]}" data-duration="{c["duration"]}" '
                        f'data-media-start="{c["mediaStart"]}" data-track-index="0"></video>'
                    )

            # Layer 1: ZV-1 A-roll (ONLY when layout is screen+pip or aroll)
            if layout in ("screen+pip", "aroll"):
                cls = "clip pip" if layout == "screen+pip" else "clip aroll-full"
                ar_clips = cover_range(by_kind["aroll"], m_in, m_out, out_cursor)
                if not ar_clips and layout == "aroll":
                    # Safety fallback to screen if A-roll doesn't cover this master range
                    for c in cover_range(by_kind["screen"], m_in, m_out, out_cursor):
                        video_tags.append(
                            f'      <video class="clip screen" src="{html.escape(c["assetPath"])}" muted playsinline preload="auto" '
                            f'data-start="{c["outStart"]}" data-duration="{c["duration"]}" '
                            f'data-media-start="{c["mediaStart"]}" data-track-index="0"></video>'
                        )
                for c in ar_clips:
                    video_tags.append(
                        f'      <video class="{cls}" src="{html.escape(c["assetPath"])}" muted playsinline preload="auto" '
                        f'data-start="{c["outStart"]}" data-duration="{c["duration"]}" '
                        f'data-media-start="{c["mediaStart"]}" data-track-index="1"></video>'
                    )

            # Layer 2: Zoom H1n audio ONLY
            au_clips = cover_range(by_kind["audio"], m_in, m_out, out_cursor)
            for idx_a, c in enumerate(au_clips):
                fade_in = min(FADE_SEC, c["duration"] / 3.0) if idx_a == 0 else 0.05
                fade_out = min(FADE_SEC, c["duration"] / 3.0) if idx_a == len(au_clips) - 1 else 0.05
                audio_tags.append(
                    f'      <audio src="{html.escape(c["assetPath"])}" preload="auto" '
                    f'data-start="{c["outStart"]}" data-duration="{c["duration"]}" '
                    f'data-media-start="{c["mediaStart"]}" data-volume="1" '
                    f'data-fade-in="{fade_in:.2f}" data-fade-out="{fade_out:.2f}" '
                    f'data-track-index="2"></audio>'
                )

            out_cursor += seg_dur

    total_dur = round(out_cursor, 4)

    card_divs = "\n".join(
        f'      <div class="chapter-card" id="{c["id"]}">'
        f'<span class="ch-eyebrow">{html.escape(c["label"])}</span>'
        f'<span class="ch-title">{html.escape(c["title"])}</span></div>'
        for c in chapter_cards
    )

    card_anim_js = "\n".join(
        f'    tl.fromTo("#{c["id"]}", {{ opacity: 0, y: 18 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power2.out" }}, {c["start"]});\n'
        f'    tl.to("#{c["id"]}", {{ opacity: 0, y: -10, duration: 0.45, ease: "power2.in" }}, {round(c["start"] + 3.2, 3)});'
        for c in chapter_cards
    )

    doc = f"""<!doctype html>
<!-- GENERATED FILE — DO NOT HAND-EDIT. Edit edit/edl.json and run `uv run scripts/build.py`. -->
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width={width}, height={height}" />
  <title>{html.escape(title)}</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      background: #0b0d12;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    }}
    #root {{
      position: relative;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      background: #0b0d12;
    }}
    .clip {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
    }}
    .clip.screen {{
      object-fit: contain;
      z-index: 1;
    }}
    .clip.aroll-full {{
      object-fit: cover;
      z-index: 2;
    }}
    .clip.pip {{
      inset: auto;
      right: 36px;
      bottom: 36px;
      width: 480px;
      height: 270px;
      object-fit: cover;
      border-radius: 16px;
      border: 2px solid rgba(255, 255, 255, 0.22);
      box-shadow: 0 18px 42px rgba(0, 0, 0, 0.55);
      z-index: 3;
    }}
    .chapter-card {{
      position: absolute;
      left: 48px;
      bottom: 48px;
      z-index: 10;
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 16px 24px;
      border-radius: 14px;
      background: rgba(15, 23, 42, 0.88);
      border-left: 4px solid #3b82f6;
      color: #f8fafc;
      opacity: 0;
      pointer-events: none;
      backdrop-filter: blur(8px);
    }}
    .ch-eyebrow {{
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #93c5fd;
      font-weight: 600;
    }}
    .ch-title {{
      font-size: 26px;
      font-weight: 700;
      line-height: 1.2;
    }}
  </style>
</head>
<body>
  <div id="root"
       data-composition-id="main"
       data-start="0"
       data-width="{width}"
       data-height="{height}"
       data-fps="{fps}"
       data-duration="{total_dur}">
    <div id="video-layer">
{chr(10).join(video_tags)}
    </div>
    <div id="audio-layer">
{chr(10).join(audio_tags)}
    </div>
    <div id="overlay-layer">
{card_divs}
    </div>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.to({{}}, {{ duration: {total_dur} }}, 0);
{card_anim_js}
    window.__timelines = window.__timelines || {{}};
    window.__timelines["main"] = tl;
    tl.seek(0);
  </script>
</body>
</html>
"""
    return doc, total_dur


def main() -> int:
    if not EDL_PATH.exists():
        print(f"ERROR: {EDL_PATH} does not exist yet.", file=sys.stderr)
        return 1

    sources_data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    sync_data = json.loads(SYNC_PATH.read_text(encoding="utf-8"))
    edl = json.loads(EDL_PATH.read_text(encoding="utf-8"))

    by_kind = build_source_intervals(sources_data["sources"], sync_data["files"])
    out_cfg = edl.get("output", {"width": 1920, "height": 1080, "fps": 30})
    w = int(out_cfg.get("width", 1920))
    h = int(out_cfg.get("height", 1080))
    fps = int(out_cfg.get("fps", 30))
    chapters: list[dict] = edl.get("chapters", [])

    # Build root composition: edit/index.html
    root_html, total_dur = render_composition_html(
        title="Session 1 — Sixth Form College",
        width=w,
        height=h,
        fps=fps,
        chapters=chapters,
        by_kind=by_kind,
        include_chapter_cards=True,
    )
    (EDIT_DIR / "index.html").write_text(root_html, encoding="utf-8")
    print(f"Generated edit/index.html (total={total_dur:.2f}s, {len(chapters)} chapters)")

    # Remove stale chapter-*.html files
    for old in EDIT_DIR.glob("chapter-*.html"):
        old.unlink()

    # Build per-chapter compositions: edit/chapter-NN.html
    for idx, ch in enumerate(chapters, start=1):
        ch_file = EDIT_DIR / f"chapter-{idx:02d}.html"
        ch_html, ch_dur = render_composition_html(
            title=f"Session 1 — {ch.get('title', ch.get('id', f'Chapter {idx}'))}",
            width=w,
            height=h,
            fps=fps,
            chapters=[ch],
            by_kind=by_kind,
            include_chapter_cards=True,
        )
        ch_file.write_text(ch_html, encoding="utf-8")
        print(f"  Generated {ch_file.relative_to(REPO_ROOT)} ({ch_dur:.2f}s) — {ch.get('title', '')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
