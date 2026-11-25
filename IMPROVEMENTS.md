# How to Make This Video Better — Session 1 & Future Sessions

Practical, evidence-based improvements grounded in what we measured from the Session 1 footage (OBS 3456×2234 @ 60 fps, Sony ZV-1 4K @ 25 fps, Zoom H1n 44.1 kHz stereo).

---

## 1. Improvements We Can Apply Right Now (In This Edit)

### Audio Polish (Biggest Immediate Quality Jump)
- **Loudness normalize to −16 LUFS** (two-pass EBU R128 `loudnorm`). The raw Zoom H1n files average low RMS (`~0.005`), which will sound quiet on YouTube or a college VLE unless normalized.
- **High-pass filter at 80 Hz** to remove room rumble, desk bumps, and HVAC hum without affecting voice clarity.
- **Check L/R balance & downmix to mono** if the H1n X/Y capsules captured the voice slightly off-center (keeps speech centered on headphones).
- **Light noise reduction / gentle compression** (e.g., 2:1–3:1 ratio) so quiet explanations and louder emphasis sit at a consistent, comfortable listening volume.
- **0.3 s audio crossfades at every cut** so edits never click or pop.

### Visual Polish (HyperFrames Advantage)
- **Smart screen zoom / focus callouts:** Your OBS capture is **3456×2234** (almost 2× wider than 1080p!). We can smoothly zoom 1.25×–1.6× onto code, terminal output, or small UI text without losing sharpness.
- **Clean 16:9 framing for 1.55:1 screen:** Instead of plain black pillars on the sides of the 3456×2234 screen, use a subtle branded dark slate backdrop (`#0b0d12`) with a thin border/shadow around the screen frame.
- **Chapter title cards & lower-thirds:** Animated HTML/GSAP chapter banners at each topic change plus a subtle persistent chapter indicator or progress bar so students can scrub to any topic.
- **Selective A-roll only where it adds value:** In `C1201.MP4`, only ~16.5% of frames had a sharp, in-frame person. Keeping A-roll strictly to approved PiP bubbles and short intro/outro cutaways keeps the video looking intentional and polished.
- **Optional burned-in or sidecar captions (`.srt` / `.vtt`):** Generated from the Whisper transcript (`edit/transcript.json`) — huge accessibility win for sixth-form students reviewing on phones or muted laptops.

### Pacing & Structure
- **Cut the 5-minute mid-session break** (`18:59:36`–`19:04:26`) and any setup fumbling, long dead air (≥8 s), or false starts.
- **Split into focused chapters (5–15 min each):** Students rewatch short, titled chapters far more than a single 2-hour block. We're already delivering both `renders/session-1-final.mp4` and per-chapter MP4s.
- **Add a 15-second cold open or hook** at the very start summarizing what students will build/learn in Session 1.

---

## 2. Improvements for Session 2 (Before & During Recording)

### Camera & Framing (Sony ZV-1)
- **Lock framing to your seated/standing zone:** Use a wider lens setting or place the tripod slightly further back with a floor/desk mark so you stay in frame >80% of the time (instead of ~16%).
- **Match frame rates across devices:** Record both OBS and Sony ZV-1 at **30 fps** (or 25 fps / 50 fps PAL). Mixing 60 fps OBS with 25 fps ZV-1 forces frame-rate conversion at 30 fps output.
- **Set the camera date/time:** The ZV-1 clock currently reads 2022. Setting accurate time makes file sorting and sync checks effortless.
- **Fix exposure & autofocus:** Use Face Priority AF (or manual focus on your chair/podium) and lock white balance so the PiP look stays consistent across the whole session.

### Audio (Zoom H1n)
- **Raise input gain slightly:** Target **−12 dB to −6 dB peaks** on the H1n meter (with limiter ON). That improves signal-to-noise ratio and reduces background hiss when normalized.
- **Keep mic distance consistent:** Place the H1n 20–30 cm from your mouth (or use a lavalier plugged into the H1n's 3.5 mm mic-in) so your voice doesn't fade when you turn toward the screen or whiteboard.
- **Do one sharp clap on camera at the start of each part** (e.g., start of Part 1 and after the break). Audio cross-correlation already worked with `z > 40`, and a visual clap gives an instant human lip-sync check too.

### Screen Capture (OBS)
- **Use a 16:9 canvas (e.g., 1920×1080 or 2560×1440):** Eliminates the 1.55:1 MacBook Retina pillarboxing completely so your screen fills 100% of the YouTube/VLE player.
- **Increase font size 20–30%** in your IDE, browser, and terminal before presenting so text stays legible on mobile screens and classroom projectors.
- **Hide notifications & cluttered desktop:** Turn on macOS Focus / Do Not Disturb and close unrelated tabs.
- **Pause OBS during breaks** (or keep one clean marker) instead of relying on 8-minute auto-splits — fewer split boundaries to stitch.

### Storage & Workflow
- **Record/render on an external NVMe SSD (≥ 250 GB free):** Local disk was at **7.7 GiB free** during Session 1 editing (with 94 GB of 4K ZV-1 footage). Recording 1080p @ 30 fps on the ZV-1 instead of 4K reduces camera file size by ~70% while still being 4× sharper than needed for a 480×270 PiP bubble!
- **Avoid trailing spaces in folder names:** Name the folder `audio` rather than `audio ` so scripts and shell commands don't need special quoting.

---

## 3. Quick Priority Checklist for Next Time

- [ ] Set OBS canvas to 16:9 (1920×1080 or 2560×1440 @ 30 fps) + bump editor font size +25%.
- [ ] Set Sony ZV-1 to 1080p @ 30 fps, correct clock, wider framing on tripod.
- [ ] Set Zoom H1n gain for −12 to −6 dB peaks + limiter ON; clap once on camera at start.
- [ ] Turn on macOS Do Not Disturb before hitting Record.
- [ ] Keep ≥ 100 GB free (or use external SSD) for raw footage + renders.
