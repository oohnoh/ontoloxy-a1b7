"""Load a video script (YAML/JSON/plain text) into scenes."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Scene:
    text: str  # shown as caption
    prompts: list[str]
    say: str | None = None  # spoken text if different (e.g. numbers spelled out)

    @property
    def speech(self) -> str:
        return self.say or self.text


@dataclass
class VideoScript:
    scenes: list[Scene]
    title: str = ""
    style: str = ""
    voice: str | None = None
    width: int = 1080
    height: int = 1920
    min_duration: float = 30.0
    max_duration: float = 60.0
    extra: dict = field(default_factory=dict)

    @property
    def image_count(self) -> int:
        return sum(len(s.prompts) for s in self.scenes)


def _scene_from(raw, images_per_scene: int, style: str) -> Scene:
    if isinstance(raw, str):
        raw = {"text": raw}
    text = raw["text"].strip()
    images = raw.get("images")
    if isinstance(images, int):
        images = [text] * images
    if not images:
        images = [text] * images_per_scene
    prompts = [f"{p}, {style}" if style else p for p in images]
    return Scene(text=text, prompts=prompts, say=(raw.get('say') or '').strip() or None)


def load_script(path: str | Path, images_per_scene: int = 2) -> VideoScript:
    """Parse a script file.

    - ``.yaml``/``.yml``/``.json``: structured script (see examples/sample.yaml)
    - anything else: plain text, one narration line per scene
    """
    path = Path(path)
    content = path.read_text(encoding="utf-8")

    if path.suffix.lower() in {".yaml", ".yml", ".json"}:
        data = json.loads(content) if path.suffix.lower() == ".json" else yaml.safe_load(content)
    else:
        lines = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.startswith("#")]
        data = {"scenes": lines}

    style = data.get("style", "")
    per_scene = int(data.get("images_per_scene", images_per_scene))
    scenes = [_scene_from(s, per_scene, style) for s in data["scenes"]]
    if not scenes:
        raise ValueError(f"{path}: no scenes found")

    size = data.get("size", [1080, 1920])
    duration = data.get("duration", [30, 60])
    known = {"scenes", "style", "images_per_scene", "size", "duration", "title", "voice"}
    return VideoScript(
        scenes=scenes,
        title=data.get("title", ""),
        style=style,
        voice=data.get("voice"),
        width=int(size[0]),
        height=int(size[1]),
        min_duration=float(duration[0]),
        max_duration=float(duration[1]),
        extra={k: v for k, v in data.items() if k not in known},
    )
