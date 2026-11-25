# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Merge per-file Whisper JSON outputs into edit/transcript.json in master time and detect dead-air/gap cuts."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = REPO_ROOT / "edit" / "sources.json"
SYNC_PATH = REPO_ROOT / "edit" / "sync.json"
WHISPER_DIR = REPO_ROOT / ".cache" / "whisper"
OUT_TRANSCRIPT = REPO_ROOT / "edit" / "transcript.json"

# Domain-specific AI training course spelling corrections for Whisper transcripts
SPELLING_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[Cc]loud\s+[Cc]ode\b"), "Claude Code"),
    (re.compile(r"\b[Cc]loud\s+[Aa][Ii]\b"), "Claude AI"),
    (re.compile(r"\b[Cc]loud\s+[Dd]esktop\b"), "Claude Desktop"),
    (re.compile(r"\b[Cc]loud\s+[Ss]onnet\b"), "Claude Sonnet"),
    (re.compile(r"\b[Cc]loud\s+[Oo]pus\b"), "Claude Opus"),
    (re.compile(r"\b[Cc]loud\s+[Hh]aiku\b"), "Claude Haiku"),
    (re.compile(r"\b[Cc]loud's\b"), "Claude's"),
    # General "cloud" -> "Claude" except when followed by cloud-infra terms
    (
        re.compile(
            r"\b[Cc]loud\b(?!\s+(?:flare|computing|storage|server|servers|service|services|provider|providers|platform|native|hosted|hosting|based|sync|drive|backup|infrastructure))"
        ),
        "Claude",
    ),
    (re.compile(r"\b[Cc]loudflare\b"), "Cloudflare"),
    (re.compile(r"\b[Aa]nthropic\b|\b[Aa]ntropic\b"), "Anthropic"),
    (re.compile(r"\b[Cc]hat\s*[Gg][PpBb][Tt]\b|\b[Cc]hachi\s*[Pp][Tt]\b"), "ChatGPT"),
    (re.compile(r"\b[Oo]pen\s*[Aa][Ii]\b"), "OpenAI"),
    (re.compile(r"\b[Gg]it\s*[Hh]ub\b"), "GitHub"),
    (re.compile(r"\b[Hh]yper\s*[Ff]rames?\b"), "HyperFrames"),
    (re.compile(r"\b[Vv][Ss]\s*[Cc]ode\b"), "VS Code"),
    (re.compile(r"\b[Aa]nti[\s-]*gravity\b"), "Antigravity"),
]


def fix_ai_spelling(text: str) -> str:
    for pat, repl in SPELLING_FIXES:
        text = pat.sub(repl, text)
    return text


def fmt_tc(sec: float) -> str:
    sec = max(0.0, sec)
    hh = int(sec // 3600)
    mm = int((sec % 3600) // 60)
    ss = sec % 60
    return f"{hh:02d}:{mm:02d}:{ss:05.2f}"


def main() -> int:
    sources_data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    sync_data = json.loads(SYNC_PATH.read_text(encoding="utf-8"))
    sync_files = sync_data["files"]
    audio_sources = [s for s in sources_data["sources"] if s["kind"] == "audio"]

    segments: list[dict] = []
    for src in audio_sources:
        stem = Path(src["filename"]).stem
        wjson = WHISPER_DIR / f"{stem}.json"
        if not wjson.exists():
            raise FileNotFoundError(f"Missing whisper output: {wjson}")
        data = json.loads(wjson.read_text(encoding="utf-8"))
        offset = sync_files[src["id"]]["masterOffset"]

        for seg in data.get("segments", []):
            m_start = round(offset + float(seg["start"]), 3)
            m_end = round(offset + float(seg["end"]), 3)
            text = fix_ai_spelling(seg.get("text", "").strip())
            if not text:
                continue
            words = []
            for w in seg.get("words", []):
                words.append(
                    {
                        "word": fix_ai_spelling(w.get("word", "")),
                        "start": round(offset + float(w["start"]), 3),
                        "end": round(offset + float(w["end"]), 3),
                    }
                )
            segments.append(
                {
                    "audioId": src["id"],
                    "start": m_start,
                    "end": m_end,
                    "startTC": fmt_tc(m_start),
                    "endTC": fmt_tc(m_end),
                    "text": text,
                    "words": words,
                }
            )

    segments.sort(key=lambda s: s["start"])

    # Detect long silences / gaps (>= 8 s) inside the OBS coverage [0, session_end]
    screen_sources = [s for s in sources_data["sources"] if s["kind"] == "screen"]
    session_end = max(
        sync_files[s["id"]]["masterOffset"] + s["duration"] for s in screen_sources
    )

    gaps: list[dict] = []
    prev_end = 0.0
    for seg in segments:
        if seg["end"] <= 0.0:
            continue
        s0 = max(0.0, seg["start"])
        if s0 - prev_end >= 8.0:
            gaps.append(
                {
                    "start": round(prev_end, 2),
                    "end": round(s0, 2),
                    "startTC": fmt_tc(prev_end),
                    "endTC": fmt_tc(s0),
                    "duration": round(s0 - prev_end, 2),
                }
            )
        prev_end = max(prev_end, min(session_end, seg["end"]))
    if session_end - prev_end >= 8.0:
        gaps.append(
            {
                "start": round(prev_end, 2),
                "end": round(session_end, 2),
                "startTC": fmt_tc(prev_end),
                "endTC": fmt_tc(session_end),
                "duration": round(session_end - prev_end, 2),
            }
        )

    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sessionEnd": round(session_end, 2),
        "segmentCount": len(segments),
        "longGaps": gaps,
        "segments": segments,
    }
    OUT_TRANSCRIPT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(segments)} segments and {len(gaps)} long gaps (>=8s) to {OUT_TRANSCRIPT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
