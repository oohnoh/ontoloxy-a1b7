"""Image providers.

Every provider implements ``generate(prompt, out_path, index)`` and writes a PNG/JPG.
"""
from __future__ import annotations

import base64
import colorsys
import os
import re
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


def split_prompt(prompt: str) -> tuple[str, str]:
    """Prompts may be ``"card text || image prompt"``; return (card text, image prompt)."""
    card, sep, img = prompt.partition("||")
    return card.strip(), (img.strip() if sep else card.strip())


class GeminiImages:
    """Google Gemini image generation (needs GEMINI_API_KEY)."""

    def __init__(self, width: int, height: int, model: str = "gemini-2.5-flash-image"):
        self.key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.model, self.width, self.height = model, width, height

    def generate(self, prompt: str, out_path: Path, index: int) -> Path:
        _, text = split_prompt(prompt)
        ratio = "9:16" if self.height > self.width else "16:9" if self.width > self.height else "1:1"
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.key},
            json={"contents": [{"parts": [{"text": text}]}],
                  "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": ratio}}},
            timeout=300,
        )
        resp.raise_for_status()
        for part in resp.json()["candidates"][0]["content"]["parts"]:
            data = part.get("inlineData") or part.get("inline_data")
            if data:
                out_path.write_bytes(base64.b64decode(data["data"]))
                return out_path
        raise RuntimeError("Gemini returned no image")


class CardImages:
    """Offline dark text cards: big headline (``[word]`` turns amber) on a grid background."""

    BG, INK, AMB = (12, 17, 24), (243, 239, 230), (255, 178, 36)

    def __init__(self, width: int, height: int, **_):
        self.width, self.height = width, height
        self.font_path = find_font()

    def generate(self, prompt: str, out_path: Path, index: int) -> Path:
        text, _ = split_prompt(prompt)
        W, H = self.width, self.height
        img = Image.new("RGB", (W, H), self.BG)
        d = ImageDraw.Draw(img)
        step = W // 12
        for x in range(0, W, step):
            d.line([(x, 0), (x, H)], fill=(24, 31, 41), width=2)
        for y in range(0, H, step):
            d.line([(0, y), (W, y)], fill=(24, 31, 41), width=2)
        d.rectangle([W * 0.08, H * 0.2, W * 0.08 + W * 0.12, H * 0.2 + 12], fill=self.AMB)

        size = int(W * 0.115)
        font = ImageFont.truetype(self.font_path, size)
        # Tokenize into (word, [(piece, highlighted)]) so "[주사]에서" stays one word.
        words = []
        # Words inside [...] are highlighted; split on spaces *outside* brackets, then wrap each
        # highlighted word separately so long highlights can still break across lines.
        for tok in re.findall(r"(?:\[[^\]]*\]|[^\s\[])+", text):
            pieces = []
            for m in re.finditer(r"\[([^\]]*)\]|([^\[]+)", tok):
                pieces.append((m.group(1), True) if m.group(1) is not None else (m.group(2), False))
            words.append(pieces)
        lines, cur, cur_w, max_w = [], [], 0, W * 0.84
        for pieces in words:
            ww = sum(d.textlength(t, font=font) for t, _ in pieces) + d.textlength(" ", font=font)
            if cur and cur_w + ww > max_w:
                lines.append(cur)
                cur, cur_w = [], 0
            cur.append(pieces)
            cur_w += ww
        lines.append(cur)
        y = H * 0.27
        for line in lines:
            x = W * 0.08
            for pieces in line:
                for t, hl in pieces:
                    d.text((x, y), t, font=font, fill=self.AMB if hl else self.INK)
                    x += d.textlength(t, font=font)
                x += d.textlength(" ", font=font)
            y += size * 1.3
        img.save(out_path)
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
    if name == "gemini":
        return GeminiImages(width, height)
    if name == "cards":
        return CardImages(width, height)
    if name == "placeholder":
        return PlaceholderImages(width, height)
    if name == "folder":
        if not folder:
            raise ValueError("--image-dir is required with --images folder")
        return FolderImages(folder)
    raise ValueError(f"unknown image provider {name!r}; choose from openai, gemini, cards, placeholder, folder")
