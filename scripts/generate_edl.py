# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Generate edit/edl.json from approved chapters, approved cuts, and approved A-roll ranges only."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EDIT_DIR = REPO_ROOT / "edit"
AROLL_PATH = EDIT_DIR / "aroll_usable.json"
EDL_PATH = EDIT_DIR / "edl.json"

# Approved 9 chapters (Checkpoint c)
CHAPTERS_SPEC = [
    ("01-welcome-setup", "Welcome, Course Setup & Portal Access", 887.17, 1500.0),
    ("02-docs-qr-skool", "Shared Docs, QR Codes & Community Onboarding", 1500.0, 2400.0),
    ("03-live-collab-race", "Live Collaboration & Rapid AI Skills (RACE)", 2400.0, 3000.0),
    ("04-agent-harnesses-claude", "AI Agent Harnesses, Claude Models & Building Agents", 3000.0, 3908.73),
    ("05-bots-vs-agents", "Bots vs. Agents — Mindset & Multi-Role Workflows", 4366.37, 5400.0),
    ("06-specialized-bots", "Designing Specialized Bots (SEO, Radar & Content)", 5400.0, 6300.0),
    ("07-ai-building-ai", "AI Building AI — Cost Per Goal & Multi-Model Keys", 6300.0, 7200.0),
    ("08-scaling-300-agents", "Scaling to 300 Agents & Real-World Bot Walkthrough", 7200.0, 7864.37),
    ("09-digital-equity-wrapup", "Digital Equity, Bot Specs & Live Approval Wrap-Up", 7887.57, 8363.75),
]

# Approved internal cuts >= 12s (Checkpoint c; pre-class setup, mid-break, and trailing silence are outside chapter bounds)
INTERNAL_CUTS: list[tuple[float, float]] = [
    (1723.75, 1736.51),  # G11 (12.8s)
    (2527.35, 2539.39),  # G12 (12.0s)
    (3229.87, 3242.51),  # G13 (12.6s)
    (4382.33, 4402.49),  # G15 (20.2s)
    (4986.65, 4999.27),  # G17 (12.6s)
    (5159.89, 5182.43),  # G19 (22.5s)
]


def subtract_cuts(start: float, end: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pieces = [(start, end)]
    for c0, c1 in cuts:
        next_pieces: list[tuple[float, float]] = []
        for p0, p1 in pieces:
            if c1 <= p0 or c0 >= p1:
                next_pieces.append((p0, p1))
            else:
                if c0 > p0 + 0.5:
                    next_pieces.append((p0, c0))
                if c1 < p1 - 0.5:
                    next_pieces.append((c1, p1))
        pieces = next_pieces
    return pieces


def split_by_aroll(
    p0: float,
    p1: float,
    approved_aroll: list[dict],
) -> list[dict]:
    """Split [p0, p1) into screen / screen+pip / aroll segments using ONLY approved A-roll ranges."""
    segs: list[dict] = []
    cursor = p0
    for ar in approved_aroll:
        a0 = float(ar["masterStart"])
        a1 = float(ar["masterEnd"])
        if a1 <= cursor:
            continue
        if a0 >= p1:
            break
        ov0 = max(cursor, a0)
        ov1 = min(p1, a1)
        if ov1 - ov0 < 1.0:
            continue
        if ov0 > cursor + 0.05:
            segs.append({"in": round(cursor, 2), "out": round(ov0, 2), "layout": "screen"})
        segs.append(
            {
                "in": round(ov0, 2),
                "out": round(ov1, 2),
                "layout": ar["suggestedLayout"],
                "arollRangeId": ar["id"],
            }
        )
        cursor = ov1
    if p1 > cursor + 0.05:
        segs.append({"in": round(cursor, 2), "out": round(p1, 2), "layout": "screen"})
    return segs


def main() -> int:
    aroll_data = json.loads(AROLL_PATH.read_text(encoding="utf-8"))
    approved_aroll = sorted(
        [r for r in aroll_data["ranges"] if r.get("approved") is True],
        key=lambda r: float(r["masterStart"]),
    )

    chapters_out: list[dict] = []
    total_dur = 0.0
    aroll_dur = 0.0
    used_aroll_ids: list[str] = []

    for cid, title, c_start, c_end in CHAPTERS_SPEC:
        pieces = subtract_cuts(c_start, c_end, INTERNAL_CUTS)
        segs: list[dict] = []
        for p0, p1 in pieces:
            segs.extend(split_by_aroll(p0, p1, approved_aroll))

        ch_dur = sum(s["out"] - s["in"] for s in segs)
        total_dur += ch_dur
        for s in segs:
            if s["layout"] in ("screen+pip", "aroll"):
                aroll_dur += s["out"] - s["in"]
                used_aroll_ids.append(s["arollRangeId"])

        chapters_out.append(
            {
                "id": cid,
                "title": title,
                "durationSec": round(ch_dur, 2),
                "segments": segs,
            }
        )
        print(f"  {cid:28s}  {ch_dur/60:5.2f} min  ({len(segs):2d} segs)  {title}")

    edl = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "output": {"width": 1920, "height": 1080, "fps": 30},
        "totalDurationSec": round(total_dur, 2),
        "arollDurationSec": round(aroll_dur, 2),
        "approvedArollIds": sorted(set(used_aroll_ids)),
        "chapters": chapters_out,
    }
    EDL_PATH.write_text(json.dumps(edl, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nWrote {EDL_PATH.relative_to(REPO_ROOT)}: "
        f"{len(chapters_out)} chapters, total={total_dur/60:.2f} min, "
        f"approved A-roll={aroll_dur:.1f}s ({len(set(used_aroll_ids))} ranges)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
