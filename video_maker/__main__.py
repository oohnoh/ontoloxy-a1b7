"""CLI: python -m video_maker examples/sample.yaml -o output/video.mp4"""
from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import Options, make_video
from .script import load_script


def main() -> None:
    ap = argparse.ArgumentParser(prog="video_maker", description=__doc__)
    ap.add_argument("script", help="script file (.yaml/.json, or .txt with one line per scene)")
    ap.add_argument("-o", "--output", default="output/video.mp4")
    ap.add_argument("--work-dir", help="cache dir for images/audio/clips (default: next to output)")
    ap.add_argument("--tts", default="edge", choices=["edge", "openai", "silent"])
    ap.add_argument("--voice", help="e.g. ko-KR-SunHiNeural, ko-KR-InJoonNeural (edge) / alloy (openai)")
    ap.add_argument("--images", default="openai", choices=["openai", "placeholder", "folder"])
    ap.add_argument("--image-dir", help="source folder for --images folder")
    ap.add_argument("--images-per-scene", type=int, default=2,
                    help="images per narration line when the script doesn't list them")
    ap.add_argument("--transition", default="slide",
                    help="slide | fade | mix | none | any ffmpeg xfade name (e.g. wipeleft)")
    ap.add_argument("--size", help="WxH, e.g. 1080x1920 (shorts) or 1920x1080")
    ap.add_argument("--duration", help="min-max seconds, e.g. 30-60")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-subtitles", action="store_true")
    ap.add_argument("--bgm", help="background music file (looped, ducked under narration)")
    ap.add_argument("--bgm-volume", type=float, default=0.12)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    script = load_script(args.script, images_per_scene=args.images_per_scene)
    if args.size:
        script.width, script.height = (int(v) for v in args.size.lower().split("x"))
    if args.duration:
        script.min_duration, script.max_duration = (float(v) for v in args.duration.split("-"))

    out = Path(args.output)
    work = Path(args.work_dir) if args.work_dir else out.with_suffix("").parent / f"{out.stem}_work"
    make_video(script, out, work, Options(
        tts_provider=args.tts, voice=args.voice, image_provider=args.images,
        image_dir=args.image_dir, transition=args.transition, fps=args.fps,
        subtitles=not args.no_subtitles, bgm=args.bgm, bgm_volume=args.bgm_volume,
        workers=args.workers,
    ))


if __name__ == "__main__":
    main()
