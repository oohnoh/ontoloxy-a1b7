"""Video rendering: Ken Burns motion per image, slide transitions, subtitles, audio mux."""
from __future__ import annotations

import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import ff

# Ken Burns motions. N = clip frame count, `on` = output frame index.
MOTIONS = {
    "zoom_in": ("1+0.18*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "zoom_out": ("1.18-0.18*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_right": ("1.15", "(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),
    "pan_left": ("1.15", "(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"),
    "pan_down": ("1.15", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*on/{n}"),
    "pan_up": ("1.15", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{n})"),
}

# xfade transition presets ("slide" is the default slide-show look).
TRANSITIONS = {
    "slide": ["slideleft", "slideup", "slideright", "slidedown", "smoothleft", "smoothup"],
    "fade": ["fade"],
    "mix": ["slideleft", "fade", "smoothup", "circleopen", "wipeleft", "slideright",
            "radial", "smoothdown", "dissolve", "zoomin"],
    "none": [],
}


@dataclass
class Shot:
    image: Path
    start: float  # seconds on the final timeline
    length: float  # visible slot length (excluding transition overlap)
    motion: str
    transition: str | None  # transition *into* the next shot


def pick_cycle(options: list[str], count: int, seed: int) -> list[str]:
    """Pick ``count`` items, never repeating the previous one back to back."""
    rnd = random.Random(seed)
    out: list[str] = []
    for _ in range(count):
        choices = [o for o in options if not out or o != out[-1]] or options
        out.append(rnd.choice(choices))
    return out


def render_clip(shot: Shot, out_path: Path, width: int, height: int, fps: int, overlap: float) -> Path:
    frames = max(2, round((shot.length + overlap) * fps))
    z, x, y = (expr.format(n=frames) for expr in MOTIONS[shot.motion])
    # Upscale 2x before zoompan so sub-pixel motion doesn't jitter.
    vf = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},setsar=1,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )
    ff.run(["-i", shot.image, "-vf", vf, "-frames:v", frames, "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "18", "-r", fps, out_path])
    return out_path


def _ass_time(t: float) -> str:
    cs = round(t * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def split_caption(text: str, max_chars: int) -> list[str]:
    """Split narration into short caption chunks at punctuation/spaces."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", text) if p.strip()]
    chunks: list[str] = []
    for part in parts:
        words, line = part.split(), ""
        for w in words:
            if line and len(line) + 1 + len(w) > max_chars:
                chunks.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        if line:
            chunks.append(line)
    return chunks or [text]


def font_family(font_file: str) -> str:
    try:
        out = subprocess.run(["fc-query", "-f", "%{family[0]}\n", font_file],
                             capture_output=True, text=True).stdout.splitlines()
        if out and out[0]:
            return out[0]
    except FileNotFoundError:
        pass
    return Path(font_file).stem


def write_ass(captions: list[tuple[float, float, str]], out_path: Path, width: int, height: int,
              font_name: str) -> Path:
    size = round(min(width, height) * 0.08)
    margin_v = round(height * (0.16 if height > width else 0.08))
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(2, size // 12)},2,2,60,60,{margin_v},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in captions:
        # Short pop-in so each caption feels animated too.
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,"
                     f"{{\\fad(120,80)\\fscx85\\fscy85\\t(0,150,\\fscx100\\fscy100)}}{text}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _esc_filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def assemble(clips: list[Path], shots: list[Shot], narration: Path, out_path: Path, total: float,
             overlap: float, fps: int, subs: Path | None = None, fonts_dir: str | None = None,
             bgm: Path | None = None, bgm_volume: float = 0.12) -> Path:
    args: list = []
    for clip in clips:
        args += ["-i", clip]
    args += ["-i", narration]
    audio_idx = len(clips)
    if bgm:
        args += ["-stream_loop", "-1", "-i", bgm]

    parts = [f"[{i}:v]settb=AVTB,fps={fps},format=yuv420p[c{i}]" for i in range(len(clips))]
    prev = "c0"
    for i in range(1, len(clips)):
        offset = shots[i].start
        trans = shots[i - 1].transition
        out = f"x{i}"
        if trans and overlap > 0:
            parts.append(f"[{prev}][c{i}]xfade=transition={trans}:duration={overlap:.3f}:"
                         f"offset={offset:.3f}[{out}]")
        else:
            # Hard cut: trim the overlap tail from the accumulated stream, then concat.
            parts.append(f"[{prev}]trim=0:{offset:.3f},setpts=PTS-STARTPTS[t{i}];"
                         f"[t{i}][c{i}]concat=n=2:v=1:a=0[{out}]")
        prev = out
    if subs:
        style_dir = f":fontsdir='{_esc_filter_path(Path(fonts_dir))}'" if fonts_dir else ""
        parts.append(f"[{prev}]ass='{_esc_filter_path(subs)}'{style_dir}[vout]")
    else:
        parts.append(f"[{prev}]null[vout]")

    if bgm:
        fade_start = max(0.0, total - 1.5)
        parts.append(f"[{audio_idx + 1}:a]volume={bgm_volume},atrim=0:{total:.3f},"
                     f"afade=t=out:st={fade_start:.3f}:d=1.5[bg];"
                     f"[{audio_idx}:a][bg]amix=inputs=2:duration=first:normalize=0[aout]")
    else:
        parts.append(f"[{audio_idx}:a]anull[aout]")

    args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
             "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             out_path]
    ff.run(args)
    return out_path
