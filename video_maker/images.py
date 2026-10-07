"""Image providers.

Every provider implements ``generate(prompt, out_path, index)`` and writes a PNG/JPG.
"""
from __future__ import annotations

import base64
import colorsys
import os
import random
import subprocess
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


def find_font(lang: str = "ko") -> str | None:
    """Locate a font that can render Korean (used for placeholders and subtitles)."""
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", f"sans:lang={lang}"],
                             capture_output=True, text=True).stdout.strip()
        if out:
            return out
    except FileNotFoundError:
        pass
    for cand in ("C:/Windows/Fonts/malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc"):
        if Path(cand).exists():
            return cand
    return None


class OpenAIImages:
    """OpenAI image generation (needs OPENAI_API_KEY)."""

    def __init__(self, width: int, height: int, model: str = "gpt-image-1", quality: str = "medium"):
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.model = model
        self.quality = quality
        ratio = width / height
        self.size = "1024x1536" if ratio < 0.9 else "1536x1024" if ratio > 1.1 else "1024x1024"

    def generate(self, prompt: str, out_path: Path, index: int) -> Path:
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"model": self.model, "prompt": prompt, "size": self.size,
                  "quality": self.quality, "n": 1},
            timeout=300,
        )
        resp.raise_for_status()
        out_path.write_bytes(base64.b64decode(resp.json()["data"][0]["b64_json"]))
        return out_path


class FolderImages:
    """Use existing images from a folder (sorted by name, cycled if too few)."""

    EXTS = {".png", ".jpg", ".jpeg", ".webp"}

    def __init__(self, folder: str | Path, **_):
        self.files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in self.EXTS)
        if not self.files:
            raise RuntimeError(f"no images found in {folder}")

    def generate(self, prompt: str, out_path: Path, index: int) -> Path:
        src = self.files[index % len(self.files)]
        Image.open(src).convert("RGB").save(out_path)
        return out_path


class PlaceholderImages:
    """Offline gradient cards with the prompt printed on them. For testing."""

    def __init__(self, width: int, height: int, **_):
        self.width, self.height = width, height
        self.font_path = find_font()

    def generate(self, prompt: str, out_path: Path, index: int) -> Path:
        rnd = random.Random(index)
        hue = rnd.random()
        c1 = [int(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.6, 0.9)]
        c2 = [int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.25) % 1, 0.7, 0.4)]
        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)
        for y in range(self.height):
            t = y / self.height
            draw.line([(0, y), (self.width, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
        for _ in range(6):
            r = rnd.randint(self.width // 10, self.width // 3)
            x, y = rnd.randint(0, self.width), rnd.randint(0, self.height)
            draw.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255), width=6)

        size = self.width // 14
        font = ImageFont.truetype(self.font_path, size) if self.font_path else ImageFont.load_default()
        text = f"#{index + 1}\n" + "\n".join(textwrap.wrap(prompt, 14))
        draw.multiline_text((self.width // 2, self.height // 2), text, font=font, fill="white",
                            anchor="mm", align="center", stroke_width=4, stroke_fill="black")
        img.save(out_path)
        return out_path


def get_provider(name: str, width: int, height: int, folder: str | None = None):
    if name == "openai":
        return OpenAIImages(width, height)
    if name == "placeholder":
        return PlaceholderImages(width, height)
    if name == "folder":
        if not folder:
            raise ValueError("--image-dir is required with --images folder")
        return FolderImages(folder)
    raise ValueError(f"unknown image provider {name!r}; choose from openai, placeholder, folder")
