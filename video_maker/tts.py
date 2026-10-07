"""Text-to-speech providers.

Every provider implements ``synth(text, out_path, speed)`` and writes an audio
file. ``speed`` is a multiplier (1.0 = normal, 1.2 = 20% faster).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import requests

from . import ff


class EdgeTTS:
    """Free Microsoft Edge neural voices (needs internet, no API key)."""

    def __init__(self, voice: str | None = None):
        self.voice = voice or "ko-KR-SunHiNeural"

    def synth(self, text: str, out_path: Path, speed: float = 1.0) -> Path:
        import edge_tts

        rate = f"{round((speed - 1) * 100):+d}%"
        out_path = out_path.with_suffix(".mp3")

        async def _go():
            await edge_tts.Communicate(text, self.voice, rate=rate).save(str(out_path))

        asyncio.run(_go())
        return out_path


class OpenAITTS:
    """OpenAI speech API (needs OPENAI_API_KEY)."""

    def __init__(self, voice: str | None = None, model: str = "gpt-4o-mini-tts"):
        self.voice = voice or "alloy"
        self.model = model
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise RuntimeError("OPENAI_API_KEY is not set")

    def synth(self, text: str, out_path: Path, speed: float = 1.0) -> Path:
        out_path = out_path.with_suffix(".mp3")
        resp = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"model": self.model, "voice": self.voice, "input": text,
                  "speed": max(0.25, min(4.0, speed)), "response_format": "mp3"},
            timeout=120,
        )
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return out_path


class SilentTTS:
    """Offline stand-in: silence whose length mimics speech. For testing timing."""

    SECONDS_PER_CHAR = 0.15

    def __init__(self, voice: str | None = None):
        pass

    def synth(self, text: str, out_path: Path, speed: float = 1.0) -> Path:
        out_path = out_path.with_suffix(".wav")
        chars = len(text.replace(" ", ""))
        dur = 0.3 + chars * self.SECONDS_PER_CHAR / speed
        ff.run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{dur:.3f}", out_path])
        return out_path


PROVIDERS = {"edge": EdgeTTS, "openai": OpenAITTS, "silent": SilentTTS}


def get_provider(name: str, voice: str | None = None):
    try:
        return PROVIDERS[name](voice=voice)
    except KeyError:
        raise ValueError(f"unknown TTS provider {name!r}; choose from {list(PROVIDERS)}") from None
