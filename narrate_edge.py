"""Synthesize narration with Microsoft Edge neural voices (free, no API key).

Reads the per-scene text build_video.py writes to <build_dir>/tts/sNN.txt and
replaces sNN.wav in place, so a rebuild with --keep-audio picks them up.

Usage: python narrate_edge.py --config path/to/video.config.json [--voice en-US-AriaNeural]

Sends narration text to a Microsoft cloud endpoint - confirm with the user
first and make sure the narration carries no sensitive data.
"""
import argparse
import asyncio
import glob
import json
import os
import subprocess
import sys

import truststore

# Corporate TLS interception presents a private root CA; trust the OS store
# rather than disabling verification. Must run before edge_tts is imported.
truststore.inject_into_ssl()

import edge_tts  # noqa: E402
import imageio_ffmpeg  # noqa: E402

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
DEFAULT_RATE = "-4%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--voice")
    ap.add_argument("--rate")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(args.config))
    tts = os.path.join(base, cfg.get("build_dir", "build"), "tts")
    voice_cfg = cfg.get("voice", {})
    voice = args.voice or voice_cfg.get("edge", DEFAULT_VOICE)
    rate = args.rate or voice_cfg.get("edge_rate", DEFAULT_RATE)

    texts = sorted(glob.glob(os.path.join(tts, "*.txt")))
    if not texts:
        sys.exit(f"No narration text in {tts}. Run build_video.py once first.")

    print(f"Voice: {voice}  rate {rate}")
    for path in texts:
        stem = os.path.splitext(path)[0]
        text = open(path, encoding="utf-8").read().strip()
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(stem + ".mp3"))
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", stem + ".mp3",
                        "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", stem + ".wav"], check=True)
        os.remove(stem + ".mp3")
        print(f"  {os.path.basename(stem)}.wav")

    print(f"Done. Now run: python build_video.py --config {args.config} --keep-audio")


if __name__ == "__main__":
    main()
