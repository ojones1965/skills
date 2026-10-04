"""Render a narrated 1080p MP4 from a timed Markdown script, frames, and a JSON config.

Requires: pillow, imageio-ffmpeg (Windows for the offline System.Speech voices).
Usage:    python build_video.py --config path/to/video.config.json [--script-timing] [--keep-audio]
            --script-timing  honour the script's timestamps instead of fitting to narration
            --keep-audio     reuse build/tts/*.wav (e.g. neural voices from narrate_edge.py)
Output:   <output>.mp4 and <output>.srt beside the config.

See ./assets/video.config.example.json for the config schema.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import wave

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

DEFAULTS = {
    "width": 1920, "height": 1080, "fps": 30, "xfade": 0.5,
    "scene_pad": 2.6, "lead_in": 0.6, "min_scene": 6.0,
    "zoom": 1.10, "zoom_card": 1.03,
    "frames_dir": "frames", "assets_dir": "assets", "build_dir": "build",
    "speech_fixes": [], "cards": [],
    "voice": {"windows": "Microsoft Zira Desktop", "rate": -1},
    "theme": {"bg": [17, 46, 81], "panel": [0, 63, 114],
              "accent": [250, 196, 45], "info": [120, 190, 255],
              "muted": [190, 205, 225]},
    "fonts": {"regular": r"C:\Windows\Fonts\segoeui.ttf",
              "bold": r"C:\Windows\Fonts\segoeuib.ttf",
              "semibold": r"C:\Windows\Fonts\seguisb.ttf"},
}


def load_config(path):
    cfg = dict(DEFAULTS)
    user = json.load(open(path, encoding="utf-8"))
    for k, v in user.items():
        cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    base = os.path.dirname(os.path.abspath(path))
    for key in ("frames_dir", "assets_dir", "build_dir", "script"):
        cfg[key] = os.path.normpath(os.path.join(base, cfg[key]))
    cfg["out_mp4"] = os.path.join(base, cfg["output"])
    cfg["out_srt"] = os.path.splitext(cfg["out_mp4"])[0] + ".srt"
    cfg["scenes"] = {int(k): v for k, v in cfg["scenes"].items()}
    return cfg


def parse_script(path):
    text = open(path, encoding="utf-8").read()
    scenes = []
    for block in re.split(r"\n(?=### Scene )", text)[1:]:
        head = re.match(r"### Scene (\d+) [—-] (.+?) · (\d+):(\d\d)[–-](\d+):(\d\d)", block)
        if not head:
            raise SystemExit(f"Unparseable scene heading:\n{block.splitlines()[0]}")
        start = int(head.group(3)) * 60 + int(head.group(4))
        end = int(head.group(5)) * 60 + int(head.group(6))
        ost = re.search(r"\*\*On-screen text:\*\* \*(.+?)\*\s*$", block, re.M)
        narr = block.split("**Narration:**", 1)[1]
        narration = " ".join(l[1:].strip() for l in narr.splitlines() if l.startswith(">")).strip()
        scenes.append(dict(num=int(head.group(1)), title=head.group(2), dur=end - start,
                           onscreen=ost.group(1) if ost else "", narration=narration))
    nums = [s["num"] for s in scenes]
    if nums != list(range(1, len(nums) + 1)):
        raise SystemExit(f"Scenes must be numbered contiguously from 1; got {nums}")
    return scenes


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def synthesize(cfg, scenes, keep_audio):
    tts = os.path.join(cfg["build_dir"], "tts")
    os.makedirs(tts, exist_ok=True)
    for s in scenes:
        spoken = s["narration"]
        for a, b in cfg["speech_fixes"]:
            spoken = spoken.replace(a, b)
        open(os.path.join(tts, f"s{s['num']:02d}.txt"), "w", encoding="utf-8").write(spoken)
    have_all = all(os.path.exists(os.path.join(tts, f"s{s['num']:02d}.wav")) for s in scenes)
    if keep_audio and have_all:
        print("  reusing existing build/tts/*.wav")
    else:
        v = cfg["voice"]
        run(["powershell", "-NoProfile", "-Command", f"""
Add-Type -AssemblyName System.Speech
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
Get-ChildItem '{tts}' -Filter *.txt | ForEach-Object {{
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice('{v["windows"]}'); $s.Rate = {v["rate"]}
  $s.SetOutputToWaveFile(($_.FullName -replace '\\.txt$', '.wav'), $fmt)
  $s.Speak((Get-Content $_.FullName -Raw -Encoding UTF8)); $s.Dispose()
}}"""])
    for s in scenes:
        with wave.open(os.path.join(tts, f"s{s['num']:02d}.wav")) as w:
            s["speech"] = w.getnframes() / w.getframerate()


def fit_timeline(cfg, scenes, script_timing):
    t = 0.0
    for s in scenes:
        fitted = cfg["lead_in"] + s["speech"] + cfg["scene_pad"]
        s["alloc"] = max(float(s["dur"]), fitted) if script_timing else max(fitted, cfg["min_scene"])
        s["t0"], s["lead"] = t, cfg["lead_in"]
        t += s["alloc"]
    return t


def build_audio(cfg, scenes):
    rate = 24000
    out = wave.open(os.path.join(cfg["build_dir"], "narration.wav"), "wb")
    out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
    for s in scenes:
        with wave.open(os.path.join(cfg["build_dir"], "tts", f"s{s['num']:02d}.wav")) as w:
            pcm = w.readframes(w.getnframes())
        lead = int(s["lead"] * rate)
        tail = int(s["alloc"] * rate) - lead - len(pcm) // 2
        out.writeframes(b"\0\0" * lead + pcm + b"\0\0" * max(tail, 0))
    out.close()


def draw_cards(cfg):
    """Render generated title/diagram/closing frames declared in config['cards']."""
    W, H = cfg["width"], cfg["height"]
    th, fonts = cfg["theme"], cfg["fonts"]
    colour = {"accent": tuple(th["accent"]), "info": tuple(th["info"])}

    def f(kind, size):
        return ImageFont.truetype(fonts[kind], size)

    for card in cfg["cards"]:
        im = Image.new("RGB", (W, H), tuple(th["bg"]))
        d = ImageDraw.Draw(im)

        if card["type"] == "closing":
            y = 170
            if card.get("logo"):
                logo = Image.open(os.path.join(cfg["assets_dir"], card["logo"])).convert("RGBA")
                lw = card.get("logo_width", 1000)
                logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
                im.paste(logo, ((W - lw) // 2, y), logo)
            d.text((W / 2, 560), card["title"], font=f("bold", 120), fill="white", anchor="mm")
            d.line((W / 2 - 180, 650, W / 2 + 180, 650), fill=tuple(th["accent"]), width=5)
            d.text((W / 2, 720), card["tagline"], font=f("semibold", 48), fill="white", anchor="mm")
            if card.get("footer"):
                d.text((W / 2, 830), card["footer"], font=f("regular", 32),
                       fill=tuple(th["muted"]), anchor="mm")

        elif card["type"] == "diagram":
            d.text((110, 80), card["title"], font=f("bold", 64), fill="white")
            for i, line in enumerate(card.get("subtitle", [])):
                d.text((112, 165 + i * 50), line, font=f("regular", 32 - i * 4),
                       fill=tuple(th["muted"]))
            for x, y, w, h, title, sub, accent in card.get("boxes", []):
                d.rounded_rectangle((x, y, x + w, y + h), 18, fill=tuple(th["panel"]),
                                    outline=colour[accent], width=3)
                d.text((x + w / 2, y + h / 2 - 22), title, font=f("semibold", 34),
                       fill="white", anchor="mm")
                d.text((x + w / 2, y + h / 2 + 26), sub, font=f("regular", 24),
                       fill=tuple(th["muted"]), anchor="mm")
            for x1, y1, x2, y2, label in card.get("arrows", []):
                d.line((x1, y1, x2, y2), fill=tuple(th["accent"]), width=5)
                a = math.atan2(y2 - y1, x2 - x1)
                for da in (2.6, -2.6):
                    d.line((x2, y2, x2 + 22 * math.cos(a + da), y2 + 22 * math.sin(a + da)),
                           fill=tuple(th["accent"]), width=5)
                if label:
                    d.text(((x1 + x2) / 2, (y1 + y2) / 2 - 26), label, font=f("regular", 22),
                           fill=(230, 230, 230), anchor="mm")
        else:
            raise SystemExit(f"Unknown card type: {card['type']}")

        im.save(os.path.join(cfg["frames_dir"], card["file"]))


def render_segments(cfg, scenes):
    W, H, FPS = cfg["width"], cfg["height"], cfg["fps"]
    seg_dir = os.path.join(cfg["build_dir"], "segments")
    os.makedirs(seg_dir, exist_ok=True)
    cards = {c["file"] for c in cfg["cards"]}
    segs = []
    for s in scenes:
        frames = cfg["scenes"][s["num"]]["frames"]
        each = s["alloc"] / len(frames)
        for i, (fname, fx, fy) in enumerate(frames):
            segs.append(dict(img=os.path.join(cfg["frames_dir"], fname), fx=fx, fy=fy,
                             alloc=each, card=fname in cards,
                             out=os.path.join(seg_dir, f"s{s['num']:02d}_{i}.mp4")))
    for k, g in enumerate(segs):
        n = int(round((g["alloc"] + (cfg["xfade"] if k < len(segs) - 1 else 0)) * FPS))
        zmax = cfg["zoom_card"] if g["card"] else cfg["zoom"]
        zp = (f"zoompan=z='1+{zmax - 1:.3f}*on/{n}':"
              f"x='(iw-iw/zoom)*{g['fx']}':y='(ih-ih/zoom)*{g['fy']}':d={n}:s={W}x{H}:fps={FPS}")
        run([FFMPEG, "-y", "-loglevel", "error", "-i", g["img"],
             "-vf", f"scale={W * 2}:{H * 2}:flags=lanczos,{zp},format=yuv420p",
             "-frames:v", str(n), "-c:v", "libx264", "-preset", "medium", "-crf", "18", g["out"]])
        print(f"  segment {k + 1}/{len(segs)}  {os.path.basename(g['out'])}  {n / FPS:.1f}s")
    return segs


def ts_ass(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def ts_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def caption_chunks(text, limit=84):
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        while len(sent) > limit:
            comma = sent.rfind(", ", 0, limit)
            cut = comma + 1 if comma > limit * 0.4 else sent.rfind(" ", 0, limit)
            out.append(sent[:cut].strip()); sent = sent[cut:].strip()
        if sent:
            out.append(sent)
    return out


def write_captions(cfg, scenes):
    # ASS colours are &HAABBGGRR - blue/green/red reversed from hex RGB.
    ass = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {cfg['width']}",
        f"PlayResY: {cfg['height']}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        "Style: Caption,Segoe UI,46,&H00FFFFFF,&H00FFFFFF,&H64000000,&H64000000,0,0,0,0,100,100,0,0,3,14,0,2,160,160,48,1",
        f"Style: OnScreen,Segoe UI Semibold,44,&H00FFFFFF,&H00FFFFFF,&H1A{cfg['theme']['bg'][2]:02X}"
        f"{cfg['theme']['bg'][1]:02X}{cfg['theme']['bg'][0]:02X},&H1A000000,0,0,0,0,100,100,0,0,3,18,0,1,70,70,190,1",
        "Style: Note,Segoe UI,26,&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,0,1,0,0,100,100,0,0,3,8,0,3,60,60,198,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    srt, n = [], 0
    for s in scenes:
        conf = cfg["scenes"][s["num"]]
        t0, t1 = s["t0"], s["t0"] + s["alloc"]
        if s["onscreen"] and not conf.get("hide_onscreen"):
            ass.append(f"Dialogue: 1,{ts_ass(t0 + 0.8)},{ts_ass(t1 - 0.6)},OnScreen,,0,0,0,,"
                       f"{{\\fad(400,300)}}{s['onscreen']}")
        if conf.get("note"):
            ass.append(f"Dialogue: 1,{ts_ass(t0 + 0.8)},{ts_ass(t1 - 0.6)},Note,,0,0,0,,{conf['note']}")
        chunks = caption_chunks(s["narration"])
        cur, total_chars = t0 + s["lead"], sum(len(c) for c in chunks)
        for c in chunks:
            d = s["speech"] * len(c) / total_chars
            ass.append(f"Dialogue: 0,{ts_ass(cur)},{ts_ass(cur + d)},Caption,,0,0,0,,{c}")
            n += 1
            srt += [str(n), f"{ts_srt(cur)} --> {ts_srt(cur + d)}", c, ""]
            cur += d
    open(os.path.join(cfg["build_dir"], "captions.ass"), "w", encoding="utf-8-sig").write("\n".join(ass) + "\n")
    open(cfg["out_srt"], "w", encoding="utf-8").write("\n".join(srt))


def assemble(cfg, segs, total):
    # ffmpeg's subtitles filter mangles Windows absolute paths: run from the
    # build dir with fonts copied in beside the .ass file.
    fonts = os.path.join(cfg["build_dir"], "fonts")
    os.makedirs(fonts, exist_ok=True)
    for path in cfg["fonts"].values():
        shutil.copy(path, fonts)
    inputs, chain, prev, offset = [], [], "[0:v]", 0.0
    for g in segs:
        inputs += ["-i", g["out"]]
    for k in range(1, len(segs)):
        offset += segs[k - 1]["alloc"]
        chain.append(f"{prev}[{k}:v]xfade=transition=fade:duration={cfg['xfade']}:"
                     f"offset={offset:.3f}[x{k}]")
        prev = f"[x{k}]"
    chain.append(f"{prev}fade=t=in:st=0:d=0.8,fade=t=out:st={total - 1.2:.3f}:d=1.2,"
                 f"subtitles=captions.ass:fontsdir=fonts,format=yuv420p[v]")
    run([FFMPEG, "-y", "-loglevel", "error", "-nostats", *inputs, "-i", "narration.wav",
         "-filter_complex", ";".join(chain), "-map", "[v]", "-map", f"{len(segs)}:a",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,apad", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(cfg["fps"]),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
         cfg["out_mp4"]], cwd=cfg["build_dir"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--script-timing", action="store_true",
                    help="honour the script's timestamps instead of fitting to narration")
    ap.add_argument("--keep-audio", action="store_true",
                    help="reuse build/tts/*.wav (e.g. neural voices from narrate_edge.py)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    os.makedirs(cfg["build_dir"], exist_ok=True)
    scenes = parse_script(cfg["script"])
    missing = [s["num"] for s in scenes if s["num"] not in cfg["scenes"]]
    if missing:
        raise SystemExit(f"Config has no frames for scenes: {missing}")

    print("Synthesizing narration...")
    synthesize(cfg, scenes, args.keep_audio)
    total = fit_timeline(cfg, scenes, args.script_timing)
    for s in scenes:
        print(f"  scene {s['num']:2d}  {ts_srt(s['t0'])[3:8]}  script {s['dur']:3d}s  "
              f"speech {s['speech']:5.1f}s  -> {s['alloc']:5.1f}s")
    print(f"Timeline: {total:.1f}s")

    build_audio(cfg, scenes)
    draw_cards(cfg)
    print("Rendering segments...")
    segs = render_segments(cfg, scenes)
    write_captions(cfg, scenes)
    print("Assembling final video...")
    assemble(cfg, segs, total)
    print(f"Done: {cfg['out_mp4']}")


if __name__ == "__main__":
    main()
