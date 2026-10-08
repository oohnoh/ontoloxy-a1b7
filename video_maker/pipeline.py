"""End-to-end pipeline: script -> TTS -> timing fit -> images -> clips -> final video."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import ff, images, render, tts
from .script import VideoScript


@dataclass
class Options:
    tts_provider: str = "edge"
    voice: str | None = None
    image_provider: str = "openai"
    image_dir: str | None = None
    transition: str = "slide"
    fps: int = 30
    gap: float = 0.25  # pause after each scene's narration (s)
    max_overlap: float = 0.45  # transition length cap (s)
    subtitles: bool = True
    bgm: str | None = None
    bgm_volume: float = 0.12
    workers: int = 4
    seed: int = 7


def log(msg: str) -> None:
    print(f"[video_maker] {msg}", flush=True)


def synth_all(provider, script: VideoScript, audio_dir: Path, speed: float) -> list[float]:
    """Synthesize every scene; return raw speech durations."""
    durs: list[float] = []
    for i, scene in enumerate(script.scenes):
        path = provider.synth(scene.speech, audio_dir / f"scene_{i:02d}", speed=speed)
        durs.append(ff.duration(path))
    return durs


def fit_timing(provider, script: VideoScript, audio_dir: Path, gap: float):
    """Pick a speech speed + per-scene pause so the total lands in [min, max] seconds."""
    n = len(script.scenes)
    speed = 1.0
    durs = synth_all(provider, script, audio_dir, speed)
    speech = sum(durs)
    lo, hi = script.min_duration, script.max_duration

    if speech + gap * n > hi:
        # Too long: speed up (cap at 1.4x so it stays intelligible).
        speed = min(1.4, speech / max(1.0, hi - 0.5 - gap * n))
    elif speech + gap * n < lo:
        # Too short: slow down slightly (min 0.9x), padding pauses covers the rest.
        speed = max(0.9, speech / (lo - gap * n))

    if abs(speed - 1.0) > 0.01:
        log(f"narration {speech:.1f}s -> re-synthesizing at {speed:.2f}x to fit {lo:.0f}-{hi:.0f}s")
        durs = synth_all(provider, script, audio_dir, speed)
        speech = sum(durs)

    if speech + gap * n < lo:
        gap = (lo + 0.5 - speech) / n
    total = speech + gap * n
    if not lo <= total <= hi:
        log(f"WARNING: total {total:.1f}s is outside {lo:.0f}-{hi:.0f}s; "
            f"{'shorten' if total > hi else 'lengthen'} the script")
    return durs, gap, speed


def build_narration(audio_dir: Path, durs: list[float], gap: float, out_path: Path) -> list[float]:
    """Pad each scene with a pause, concat into one WAV; return per-scene lengths."""
    scene_files = sorted(p for p in audio_dir.glob("scene_*") if p.suffix in {".mp3", ".wav"}
                         and not p.stem.endswith("_pad"))
    padded = []
    for i, (src, dur) in enumerate(zip(scene_files, durs)):
        dst = audio_dir / f"scene_{i:02d}_pad.wav"
        ff.run(["-i", src, "-af", f"apad=whole_dur={dur + gap:.3f}", "-ar", 44100, "-ac", 2, dst])
        padded.append(dst)
    inputs = sum((["-i", p] for p in padded), [])
    concat = "".join(f"[{i}:a]" for i in range(len(padded))) + f"concat=n={len(padded)}:v=0:a=1[a]"
    ff.run([*inputs, "-filter_complex", concat, "-map", "[a]", out_path])
    return [ff.duration(p) for p in padded]


def make_video(script: VideoScript, out_path: Path, work_dir: Path, opts: Options) -> Path:
    ff.require_ffmpeg()
    W, H = script.width, script.height
    for sub in ("audio", "images", "clips"):
        (work_dir / sub).mkdir(parents=True, exist_ok=True)
    log(f"{len(script.scenes)} scenes, {script.image_count} images, {W}x{H}")

    # 1) Narration + timing fit
    voice = opts.voice or script.voice
    speaker = tts.get_provider(opts.tts_provider, voice=voice)
    for old in (work_dir / "audio").glob("scene_*"):
        old.unlink()
    durs, gap, speed = fit_timing(speaker, script, work_dir / "audio", opts.gap)
    narration = work_dir / "narration.wav"
    scene_lens = build_narration(work_dir / "audio", durs, gap, narration)
    total = sum(scene_lens)
    log(f"narration {total:.1f}s (speed {speed:.2f}x, pause {gap:.2f}s)")

    # 2) Images (cached: existing files are reused on re-runs)
    painter = images.get_provider(opts.image_provider, W, H, folder=opts.image_dir)
    prompts = [p for s in script.scenes for p in s.prompts]
    img_paths = [work_dir / "images" / f"img_{i:03d}.png" for i in range(len(prompts))]

    def _gen(i: int) -> None:
        if not img_paths[i].exists():
            painter.generate(prompts[i], img_paths[i], i)
            log(f"image {i + 1}/{len(prompts)} done")

    with ThreadPoolExecutor(opts.workers) as pool:
        list(pool.map(_gen, range(len(prompts))))

    # 3) Timeline: each scene's audio length is split evenly across its images
    n_imgs = len(prompts)
    motions = render.pick_cycle(list(render.MOTIONS), n_imgs, opts.seed)
    trans_opts = render.TRANSITIONS.get(opts.transition, [opts.transition])
    transitions = render.pick_cycle(trans_opts, n_imgs, opts.seed + 1) if trans_opts else [None] * n_imgs
    shots: list[render.Shot] = []
    t, k = 0.0, 0
    for scene, length in zip(script.scenes, scene_lens):
        slot = length / len(scene.prompts)
        for _ in scene.prompts:
            shots.append(render.Shot(img_paths[k], t, slot, motions[k], transitions[k]))
            t += slot
            k += 1
    shots[-1].transition = None
    overlap = 0.0 if not trans_opts else min(opts.max_overlap, min(s.length for s in shots) * 0.35)

    # 4) Animated clips (parallel ffmpeg)
    clip_paths = [work_dir / "clips" / f"clip_{i:03d}.mp4" for i in range(n_imgs)]
    with ThreadPoolExecutor(opts.workers) as pool:
        list(pool.map(lambda i: render.render_clip(shots[i], clip_paths[i], W, H, opts.fps, overlap),
                      range(n_imgs)))
    log(f"rendered {n_imgs} animated clips")

    # 5) Captions
    subs = fonts_dir = None
    if opts.subtitles:
        font = images.find_font()
        captions = []
        start = 0.0
        for scene, speech_len, length in zip(script.scenes, durs, scene_lens):
            chunks = render.split_caption(scene.text, 16 if H > W else 28)
            weights = [len(c) for c in chunks]
            t = start
            for chunk, w in zip(chunks, weights):
                d = speech_len * w / sum(weights)
                captions.append((t, t + d, chunk))
                t += d
            start += length
        subs = render.write_ass(captions, work_dir / "captions.ass", W, H,
                                render.font_family(font) if font else "Sans")
        fonts_dir = str(Path(font).parent) if font else None

    # 6) Final mux
    out_path.parent.mkdir(parents=True, exist_ok=True)
    render.assemble(clip_paths, shots, narration, out_path, total, overlap, opts.fps, subs=subs,
                    fonts_dir=fonts_dir, bgm=Path(opts.bgm) if opts.bgm else None,
                    bgm_volume=opts.bgm_volume)

    timeline = [{"image": s.image.name, "start": round(s.start, 2), "length": round(s.length, 2),
                 "motion": s.motion, "transition": s.transition} for s in shots]
    (work_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    log(f"done: {out_path} ({ff.duration(out_path):.1f}s)")
    return out_path
