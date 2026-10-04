---
name: narrated-demo-video
description: 'Render a narrated product-demo MP4 from still frames and a script: neural TTS voiceover with word-timed burned-in captions, Ken Burns motion, cross-fades, generated title/closing cards, and a verification pass. Config-driven (video.json) with bundled Python + ffmpeg scripts. USE FOR: "make the video", "render the demo video", "narrated demo", "turn the video script into an MP4", "voiceover walkthrough", "product tour video", "add captions to demo", "Ken Burns screenshots video". Usually follows app-discovery-whitepaper (VIDEO-SCRIPT.md + screenshots). DO NOT USE FOR: writing the script itself (use app-discovery-whitepaper), live screen recording, or editing existing footage.'
argument-hint: 'Path to VIDEO-SCRIPT.md or a folder of 16:9 frames'
---

# Narrated Demo Video

Turns a timed video script and a set of still frames into a finished MP4:
neural narration, captions cut on real word boundaries, slow Ken Burns motion,
cross-fades, opening/closing cards. Everything is driven by one `video.json`
so a re-render after a script edit is a single command.

## When to Use
- A `VIDEO-SCRIPT.md` exists (typically from `app-discovery-whitepaper`) and the
  user wants the actual video.
- The user has screenshots and narration text and wants a captioned MP4.
- Re-rendering after narration, caption, or frame changes.

## Toolchain
| Need | Check | Install |
|---|---|---|
| ffmpeg + ffprobe (with libass) | `Get-Command ffmpeg` | `winget install Gyan.FFmpeg` |
| Python 3.10+ | `py -3 --version` | — (Windows `python` may be a Store stub; use `py -3`) |
| Neural TTS | `py -3 -c "import edge_tts"` | `py -3 -m pip install edge-tts` |
| Title cards | `py -3 -c "import PIL"` | `py -3 -m pip install pillow` |
| Corporate TLS proxy | TTS fails `CERTIFICATE_VERIFY_FAILED` | `py -3 -m pip install truststore` (auto-used) |

**Ask before narrating.** `edge-tts` sends narration text to a Microsoft cloud
endpoint. Offer: neural (cloud), offline Windows SAPI (robotic), or silent with
captions only. Never put sensitive data in narration.

## Procedure

### 1. Set up the project folder
```
<project>/video/
├── video.json      # copy from ./assets/video.example.json
├── frames/         # 16:9 stills referenced by video.json
├── audio/          # written by narrate.py
└── work/           # intermediates (gitignore this and audio/*.mp3)
```

### 2. Capture dedicated 16:9 frames — not the white-paper screenshots
Tall full-page PNGs upscale and distort. Capture per-scene frames from the
live app with `run_playwright_code`:

```js
const { w } = await page.evaluate(() => ({ w: window.innerWidth }));  // setViewportSize is ignored
const clip = { x: 0, y: 0, width: w - 1, height: Math.round((w - 1) * 9 / 16) };
await page.addStyleTag({ content: `*{animation-duration:0s!important;transition:none!important}
  .reveal,[class*="reveal"],[class*="fade"]{opacity:1!important;transform:none!important}
  nav,.top-nav,header{background:#0a1020!important}` });   // sticky translucent nav bleeds text
await page.evaluate(y => window.scrollTo(0, y), 1070); await page.waitForTimeout(1400);
await page.screenshot({ path: 'C:\\...\\video\\frames\\03-kpi.png', clip });
```
- Find section offsets first (`getBoundingClientRect().top + scrollY`) instead of guessing.
- Canvas/WebGL panels (graphs, "live core" widgets) need 10–15 s to settle — wait, then capture.
- Chat panes scroll inside a container: set `el.scrollTop`, not `window.scrollTo`.
- **Re-apply PII redaction on every re-capture** — it is a DOM edit, not persistent.
  Spot-check redacted frames with `view_image`.
- Output resolution should not exceed the capture size: a ~1200 px wide
  browser → render 1280×720, not 1080p.

### 3. Write `video.json`
One entry per script scene. See [video.example.json](./assets/video.example.json).

| Field | Meaning |
|---|---|
| `narration` | Caption text, and spoken text unless `speak` is set |
| `speak` | Optional pronunciation override (`"S Q L"`, `"V A"`). Captions still show `narration`; timings are aligned across the difference |
| `frames` | Stills shown in order; scene time is split evenly with 0.5 s cross-fades |
| `blur_intro` | First frame starts blurred and dim, resolving mid-shot (problem/hook beat) |
| `titles[]` | On-screen text: `at` = seconds after the narration starts, `dur`, `style` = `Kicker` (top), `Lower` (lower-third), `Caption` |

Round numbers in narration; put exact values in `titles`. Add an "as of" lower-third.

### 4. Generate narration
```powershell
py -3 <skill>/scripts/narrate.py <project>/video
```
Writes `audio/scene-NN.mp3` and `audio/manifest.json` with durations and
word-timed caption cues. Valid clips whose text is unchanged are reused;
`--force` regenerates everything. Each clip is checked at 1.6–3.4 words/sec
and retried — edge-tts occasionally returns a truncated stream (3 s for 100
words) with no error.

### 5. Render cards and video
```powershell
py -3 <skill>/scripts/make_cards.py <project>/video
py -3 <skill>/scripts/build_video.py <project>/video
```
The builder runs a preflight check (ffmpeg present, every frame/card exists,
every scene has narration) before encoding anything. **Scene length is set by
the real narration**, plus 0.6 s lead and tail, so the final runtime usually
differs from the script's estimate. Update the script's timestamps to match
afterwards.

Caption-only changes: `build_video.py <dir> --recaption` re-burns captions
and titles onto the existing cut without re-encoding the scenes.

### 6. Verify before reporting done
```powershell
ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,width,height -of default=nw=1 demo.mp4
foreach ($t in 8,40,150,300) { ffmpeg -y -v error -ss $t -i demo.mp4 -frames:v 1 "check_$t.png" }
```
View several stills with `view_image` and confirm:
- one caption at a time, punctuated, never stacked
- kicker titles don't collide with the app's own headings
- redacted content is still redacted in the render
- the closing card is legible and carries the "as of" date

Then delete the `check_*.png` stills and state the final runtime, resolution,
file size, and any deviation from the script.

## Pitfalls
1. **`zoompan` + `-loop 1` hangs.** zoompan emits `d` frames *per input frame*,
   so a looped still multiplies output toward infinity; the first clip sits at
   0 bytes forever. Feed the still once and cap with `-frames:v`. Pre-scale to
   1.5× output, not 2560 px.
2. **edge-tts 7.x defaults to `SentenceBoundary`.** Pass
   `boundary="WordBoundary"` or no per-word timings come back.
3. **Word boundaries drop punctuation, and `speak` overrides change the token
   count.** `narrate.py` sequence-aligns spoken words to the caption text so
   captions keep punctuation and show "SQL", not "S Q L".
4. **Overlapping cue times stack captions.** libass renders every active event;
   clamp each cue's end to the next cue's start.
5. **Windows paths break the `subtitles` filter.** The drive-letter colon is
   parsed as an option separator. Run that ffmpeg call with `cwd` set to the
   ASS file's folder and pass a bare filename.
6. **`amix` wants `duration=longest`,** not `long`.
7. **Corporate TLS inspection.** Use `truststore` (Windows cert store). Never
   disable certificate verification.
8. **Long renders get backgrounded by the terminal tool.** Check progress via
   file sizes in `work/`. A stage frozen at 0 bytes is hung, not slow.
