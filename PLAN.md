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
- [x] Every source file has a `sync.json` entry with confidence ≥ 8 (or a documented manual offset). — **Evidence:** `edit/sync.json` (22/22 files synced via `uv run scripts/sync.py`, `flaggedCount: 0`, z-scores `24.00–219.87`, ZV-1 drift `-6.35 ms` / `-3.29 ms` = `≤ 0.16` frames over 60+ min, `rate: 1.0`).
- [x] Lip sync within ±1 frame at three points of the final render. — **Evidence:** 3 × 10 s verification clips (`renders/sync_check/sync_check_{1_start,2_middle,3_end}.mp4` at master `411.93 s`, `4579.31 s`, `8248.49 s`) visually approved in Google Chrome at Checkpoint a; drift measured across 5 windows per camera file (`-1.24 ms` to `+8.15 ms` = `±0.2` frames).
- [x] Only Zoom H1n audio is audible. No camera or OBS audio bleeds into the mix. — **Evidence:** `scripts/build.py` sets `muted` on every `<video>` tag and emits `<audio>` exclusively from `ZOOM0030.m4a` / `ZOOM0031.m4a` (two-pass `-16 LUFS` + 80 Hz HPF via `scripts/polish_audio.py`); `ffprobe` confirms `audio_streams=1` on all 9 chapter MP4s and `renders/session-1-final.mp4`.
- [x] Screen capture is on screen for the whole video except approved A-roll cutaways. — **Evidence:** `edit/edl.json` (9 chapters, `6,902.98 s` = `115.05 min`) uses `screen` or `screen+pip` everywhere except the 4 approved closing cutaways (`R27–R30`, `48 s` total).
- [x] A-roll only appears in human-approved ranges where the presenter is in frame. — **Evidence:** `edit/aroll_usable.json` (`30` candidate ranges detected via `scripts/presence.py`, `16` active-speech ranges approved at Checkpoint b: `R10–R13, R15–R16, R19–R20, R22–R24, R26–R30`, `280.0 s` total); automated verification confirmed `0` unapproved A-roll segments in `edit/edl.json`.
- [x] `edit/index.html` is regenerated from `edl.json` (never hand-edited) and passes `npm run check`. — **Evidence:** `uv run scripts/build.py` generates `edit/index.html` + `edit/compositions/chapter-01.html`…`09.html`; `cd edit && npm run check` passed with **0 errors, 0 warnings** across Lint, Runtime, Layout (9 samples), Motion, Craft, and Audio.
- [x] No media files committed to git. — **Evidence:** `.gitignore` ignores `*.mp4, *.MP4, *.mov, *.MOV, *.mkv, *.MKV, *.wav, *.WAV, renders/, edit/assets/, edit/.hyperframes/, edit/.thumbnails/, .cache/`; verified with `git status` before every commit.

## 6. Actual Execution Summary & Deviations from Initial Plan

- **Completed deliverables (reproducible from `edit/edl.json` alone):**
  - `renders/session-1-final.mp4` (`742.9 MB`, `6903.12 s` = `115.05 min`, `1920×1080 @ 30 fps`, 1 audio stream)
  - 9 per-chapter MP4s in `renders/chapters/01-welcome-setup.mp4` … `09-digital-equity-wrapup.mp4` (`742 MB` combined)
  - Backed up to Google Drive via Azure Key Vault (`scripts/backup_gdrive.py`) → `gdrive-shared:secondbrain/backups/session-1-sixth-form-college/renders`
- **Deviations & improvements applied:**
  1. **Chapter compositions moved to `edit/compositions/chapter-NN.html`:** HyperFrames `0.9.96` `npm run check` flags `multiple_root_compositions` if chapter HTML files live beside `edit/index.html`. Moving them to `edit/compositions/` achieved 0 errors, 0 warnings.
  2. **Chapter output directory:** Rendered per-chapter files to `renders/chapters/<chapter-id>.mp4` (matching prompt goal) and concatenated with `ffmpeg -f concat -c copy` to `renders/session-1-final.mp4`.
  3. **Audio polish format:** Two-pass `-16 LUFS` + 80 Hz HPF (`scripts/polish_audio.py`) saved normalized Zoom H1n tracks as 256 kbps AAC (`edit/assets/audio_norm/ZOOM0030.m4a`, `ZOOM0031.m4a`, `252 MB` total vs. `1.4 GB` WAV) — raw H1n tracks measured `-39.30` and `-40.52 LUFS`, so normalization also resolved Whisper's quiet-audio hallucination loop on Part 1 (`--condition_on_previous_text False`).
  4. **Branding & AI-course spelling:** Red & white animated GSAP chapter title cards (28 px+ mobile-readable typography) and domain spelling normalization (`Claude`, `Claude Code`, `Anthropic`, `ChatGPT`, `OpenAI`, `GitHub`, `HyperFrames`) in `scripts/merge_transcript.py`.
  5. **`autoProxy: false` in `edit/hyperframes.json`:** Prevented multi-gigabyte proxy generation while local disk was initially at `7.6 GiB` free (later freed to `126 GiB`).
  6. **Web portal & Skool prep:** Added shared navigation (`nav.js`) across `index.html`, `specs.html`, `improvements.html`, `recommendations.html`, `render.html`, `eta.html`, `performance.html`, and `result.html`, plus `edit/skool_chapters.json` for Skool classroom upload under `"2026 - November 25"`.
  7. **Performance:** Full 115.05-min Phase E render completed in **1 h 52 m 03 s** (`0.97×` real-time on Apple M1 Max hardware GPU). Total end-to-end session wall-clock time (including human review checkpoints & extra docs): **~3 h 26 m** (active compute: **~2 h 22 m**).
