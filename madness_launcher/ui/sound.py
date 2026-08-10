"""The new-message notification.

The tone is synthesised at startup rather than shipped as an audio file: it
keeps the project free of binary assets, and a soft decaying sine is a couple of
dozen lines. It is deliberately quiet and short — something you can leave on all
evening without wanting to turn it off.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from PySide6.QtCore import QUrl

from .. import paths

try:
    from PySide6.QtMultimedia import QSoundEffect

    SOUND_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the installed wheel
    QSoundEffect = None  # type: ignore
    SOUND_AVAILABLE = False

SAMPLE_RATE = 44100
FREQUENCY = 784.0      # G5: audible over speech, well short of shrill.
DURATION = 0.11
AMPLITUDE = 0.22       # Quiet by design.

_effect = None


def _write_tone(path: Path) -> None:
    frames = int(SAMPLE_RATE * DURATION)
    attack = int(SAMPLE_RATE * 0.006)   # A click without a short fade-in.
    samples = bytearray()

    for i in range(frames):
        t = i / SAMPLE_RATE
        # Exponential decay gives a struck-bell shape rather than a buzz.
        envelope = math.exp(-t * 26.0)
        if i < attack:
            envelope *= i / attack
        value = math.sin(2.0 * math.pi * FREQUENCY * t) * envelope * AMPLITUDE
        samples += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(samples))


def tone_path() -> Path:
    path = paths.app_root() / "sounds" / "notify.wav"
    if not path.is_file():
        _write_tone(path)
    return path


def notification():
    """The shared sound effect, or None when audio is unavailable."""
    global _effect
    if not SOUND_AVAILABLE:
        return None
    if _effect is None:
        _effect = QSoundEffect()
        _effect.setSource(QUrl.fromLocalFile(str(tone_path().resolve())))
        _effect.setVolume(0.35)
    return _effect


def play_notification() -> None:
    effect = notification()
    if effect is not None:
        effect.play()
