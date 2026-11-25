# Edit Plan — Sixth Form College, Session 1 (HyperFrames)

> **Handover brief for the implementing agent (Antigravity).** This document is the plan only.
> No pipeline code exists yet. Build it in this repo following the phases below.

## 1. Goal

Turn the recording of Session 1 (25 Nov 2026, ~17:52–20:11) into an edited video built with
[HyperFrames](https://hyperframes.heygen.com) (HTML compositions → MP4, `hyperframes@0.9.96`).

Editorial rules from the presenter:

1. **Screen capture (OBS) leads.** It is the primary picture for the whole video.
2. **Audio = Zoom H1n only.** The camera audio is far from the speaker and must never be heard.
   OBS audio is also muted in the final mix (used only for syncing).
3. **A-roll (Sony ZV-1) is used only where the presenter is in frame and the shot is usable.**
   Most of the A-roll is unusable (presenter out of frame / poor quality). Use the good bits as
   picture-in-picture or short full-frame cutaways.

## 2. Source inventory (measured with ffprobe)

Footage root: `~/Movies/sixth from first session/production/` (**not** in git — 95 GB).

| Source | Folder | Files | Format | Total length | Notes |
|---|---|---|---|---|---|
| OBS screen capture | `screencapture/` | 18 × ~8 min (`2026-11-25 17-51-53.mp4` … `20-08-44.mp4`) | H.264 3456×2234 @ 60 fps, AAC 48 kHz | ≈ 2 h 20 m | Filenames = wall-clock start time. Files are contiguous splits. Last two are short (206 s, 172 s at 18-56 and 20-08). |
| Sony ZV-1 A-roll | `aroll/` | `C1201.MP4` (60:26), `C1202.MP4` (66:34) | H.264 3840×2160 @ 25 fps, PCM s16be | ≈ 2 h 07 m, **94 GB** | Camera clock is wrong (says 2022) — timestamps unusable. Audio is distant (sync only). PCM-in-MP4 audio won't play in Chrome; always `muted`. |
| Zoom H1n audio | `audio /` ⚠️ folder name has a **trailing space** | `ZOOM0030.WAV` (68:59), `ZOOM0031.WAV` (66:57) | PCM s16le 44.1 kHz stereo | ≈ 2 h 16 m | **The only audio in the final mix.** `ZOOM0032.WAV` is 1.2 s — ignore. Recorder clock also unreliable. |

Machine constraints:
- **Disk is ~100 % full (≈ 7.6 GB free).** Do not create full-length proxies of everything.
  Link originals in place; transcode only the selected A-roll ranges, or move work to an external drive.
- `ffmpeg`, `ffprobe`, `node 26`, `uv`, `whisper` / `whisper-cli` are installed.
  System Python is 3.15 with no numpy → run Python tools via `uv run` with inline deps (pin Python ≤ 3.13).

## 3. Target repo layout

```
config.json              # footage root, folder names (incl. "audio "), ignore list, output size
scripts/
  ingest.py              # probe all sources → edit/sources.json; symlink media into edit/assets/
  sync.py                # audio cross-correlation → edit/sync.json (offsets + confidence)
  presence.py            # find usable A-roll ranges → edit/aroll_usable.json (+ review thumbnails)
  transcribe.sh          # whisper on the Zoom audio → edit/transcript.json (chapters/captions)
  build.py               # edl.json + sync + sources → edit/index.html (+ edit/chapter-NN.html)
edit/                    # the HyperFrames project (npx hyperframes init edit --example blank)
  index.html             # GENERATED root composition — do not hand-edit
  edl.json               # edit decision list — the file humans edit
  assets/                # symlinks to originals (gitignored)
  hyperframes.json, package.json, meta.json
index.html               # project plan page (this plan, served on Fly.io)
.gitignore               # edit/assets/, .cache/, renders/, *.mp4, *.wav
```

## 4. Phases

### Phase 0 — Ingest
- Read `config.json`. Resolve `~` and allow `FOOTAGE_ROOT` env override (for an external drive).
- ffprobe every file → `edit/sources.json` (`kind`, `path`, `duration`, `fps`, `size`).
- OBS: parse start time from filename (`%Y-%m-%d %H-%M-%S`) → `nominalStart` in seconds from the first file.
- Symlink originals into `edit/assets/{screen,aroll,audio}/` with **space-free names**
  (e.g. `screen/2026-11-25_17-51-53.mp4`, `audio/ZOOM0030.WAV`). Quote paths everywhere — `audio ` has a trailing space.

### Phase 1 — Sync (the critical step)
No reliable shared clock exists, so align everything by **audio cross-correlation**.

- **Master timeline:** t = 0 at the start of OBS file 1 (17:51:53).
- Extract mono 8 kHz audio from every file (`ffmpeg -vn -ac 1 -ar 8000 -f s16le`), cache in `.cache/`.
- Convert to a 1 kHz onset envelope (frame |x| mean → log → subtract 0.5 s moving average → z-normalise).
  This is robust across very different mics (H1n close, ZV-1 far, laptop).
- Steps:
  1. Build an OBS canvas from filename start times; FFT-correlate each Zoom file against it (full search) → Zoom offsets.
  2. Build a Zoom canvas; refine each OBS file start in a ±3 s window (filenames are only second-accurate, ~0.7 s drift seen between splits).
  3. FFT-correlate each ZV-1 file against the Zoom canvas (full search) → A-roll offsets.
- Output `edit/sync.json`: per file `masterOffset` (master time at which file t=0 plays) and `confidence` (peak z-score).
  Flag anything with z < 8 for manual check.
- **Fallback:** if OBS has no room audio (desktop-only), the OBS↔Zoom match fails → ask the presenter
  for a visible/audible sync point (a clap or a slide change) and enter the offset manually in `sync.json`.
- **Verify:** render 3 × 10 s check clips (start, middle, end) with Zoom audio over the A-roll picture and check lip sync. Allow ±1 frame at 25 fps. Watch for drift between the 44.1 kHz recorder and the camera over 60 min. If drift is above 1 frame, store a linear `rate` correction per file.

### Phase 2 — A-roll usability detection
- Sample decoded keyframes every 2 s at 640×360 (`-skip_frame nokey -vf fps=1/2,scale=640:360`); avoid full 4K decode.
- Per sample: person/face present (OpenCV HOG people detector + Haar frontal/profile face, or MediaPipe),
  sharpness (Laplacian variance), brightness/exposure.
- Smooth (majority over 5 samples), keep ranges ≥ 8 s with good sharpness → `edit/aroll_usable.json`
  (source time + master time via `sync.json`).
- Save one thumbnail per range in `.cache/review/` for a quick human yes/no pass. Students may trigger person detection,
  so **every range needs a human OK** before it goes into the EDL (`"approved": true`).

### Phase 3 — Transcript and chapters
- `whisper` on the Zoom audio (both files) → `edit/transcript.json` with word timestamps, converted to master time.
- Use it to propose chapters (topic changes), cut points for dead air or setup time, and optional captions.

### Phase 4 — EDL and HyperFrames composition
`edit/edl.json` is the single source of editorial truth. All times are in **master time**:

```json
{
  "output": { "width": 1920, "height": 1080, "fps": 30 },
  "chapters": [
    { "id": "01-intro", "title": "Welcome",
      "segments": [
        { "in": 35.0, "out": 412.5, "layout": "screen" },
        { "in": 412.5, "out": 440.0, "layout": "screen+pip" },
        { "in": 440.0, "out": 452.0, "layout": "aroll" }
      ] }
  ]
}
```

Layouts:
- `screen`: OBS full frame, `object-fit: contain` (3456×2234 is 1.55:1, so it gets thin pillars on a dark background).
- `screen+pip`: screen, plus A-roll in a rounded 480×270 box bottom-right, only for approved ranges.
- `aroll`: full-frame camera cutaway (short, approved ranges only).

`build.py` ripple-concatenates the segments into output time. For each segment and layer it finds the covering
source file(s), splitting at file boundaries, and emits:

```html
<video class="clip" src="assets/screen/2026-11-25_18-08-00.mp4" muted
       data-start="OUT_T" data-duration="D" data-media-start="SRC_T" data-track-index="0"></video>
<video class="clip pip" src="assets/aroll/C1201.MP4" muted
       data-start="OUT_T" data-duration="D" data-media-start="SRC_T" data-track-index="1"></video>
<audio src="assets/audio/ZOOM0030.WAV" data-start="OUT_T" data-duration="D"
       data-media-start="SRC_T" data-volume="1" data-track-index="2"></audio>
```

Rules:
- `SRC_T = masterTime − masterOffset`.
- Every `<video>` is `muted`. The Zoom `<audio>` is the only sound.
- Add 0.3 s `data-fade-in`/`data-fade-out` on audio at every cut.
- Root `#root` has `data-composition-id="main"`, a `data-duration` equal to the total output, and registers a paused GSAP timeline on `window.__timelines["main"]`.
- Also write `edit/chapter-NN.html` (same asset paths) so each chapter renders on its own. A 2 h browser-captured render is slow, so render per chapter and concat.
- Optional: lower-thirds and chapter title cards as GSAP-animated HTML overlays; captions from the transcript.

### Phase 5 — Audio polish
- Loudness-normalise Zoom audio to −16 LUFS (YouTube/online) with `hyperframes normalize-audio` or `ffmpeg loudnorm` (two-pass).
- Optional light denoise / high-pass at 80 Hz. Downmix to mono if the H1n stereo image is unbalanced.

### Phase 6 — Review and render
1. `cd edit && npm run check` (lint, runtime, layout).
2. `npx hyperframes snapshot --at …` at each cut and PiP entry to check framing.
3. `npx hyperframes preview --background` to review in Studio. Open in **Google Chrome**.
4. Render each chapter (`npx hyperframes render -c chapter-NN.html -o renders/chapter-NN.mp4`), then
   `ffmpeg -f concat` to `renders/session-1-final.mp4`. Write renders to an external drive if local space is short.
5. Spot-check sync at the start, middle and end of the final file.

## 5. Acceptance criteria
- [ ] Every source file has a `sync.json` entry with confidence ≥ 8 (or a documented manual offset).
- [ ] Lip sync within ±1 frame at three points of the final render.
- [ ] Only Zoom H1n audio is audible. No camera or OBS audio bleeds into the mix.
- [ ] Screen capture is on screen for the whole video except approved A-roll cutaways.
- [ ] A-roll only appears in human-approved ranges where the presenter is in frame.
- [ ] `edit/index.html` is regenerated from `edl.json` (never hand-edited) and passes `npm run check`.
- [ ] No media files committed to git.

## 6. Open questions for the presenter
1. Output target: one long video, or chapters (e.g. for YouTube or the college's VLE)?
2. Is there a clap or another clear sync point in the recording? (Needed only if OBS has no room audio.)
3. Preferred A-roll treatment: PiP bubble, full cutaways, or both?
4. Branding: college name, logo or colours for title cards and lower-thirds?
5. Remove student voices or faces for privacy? (They affect the transcript, captions and A-roll choice.)
