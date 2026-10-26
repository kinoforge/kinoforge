"""Narration-driven timing used before and after voiceover exists."""

import math
import re

from kinoforge.segments.story.audio_modes import uses_native_audio


class NarrationTimer:
    """Estimates and measures scene duration. Reading-speed constants are assumptions, not
    limits: real TTS duration replaces them as soon as voiceover exists."""

    _WORD_RE = re.compile(r"\b[\w’']+\b", re.UNICODE)
    _CJK_RE = re.compile(r"[㐀-䶿一-鿿぀-ヿ가-힯]")
    _PAUSE_RE = re.compile(r"[.!?。！？;:]")

    LATIN_WORDS_PER_SECOND = 2.2
    CJK_CHARACTERS_PER_SECOND = 4.0
    PAUSE_SECONDS = 0.18
    MAX_ESTIMATED_PAUSE_SECONDS = 4.0
    MIN_SCENE_SECONDS = 1.0
    MAX_ASKED_SECONDS = 60.0

    @classmethod
    def narration_seconds(cls, text: object) -> float:
        """Estimate speech length without imposing a target or maximum."""
        value = str(text or "")
        cjk_chars = len(cls._CJK_RE.findall(value))
        latin_words = len(cls._WORD_RE.findall(cls._CJK_RE.sub(" ", value)))
        pauses = len(cls._PAUSE_RE.findall(value))
        estimate = (
            latin_words / cls.LATIN_WORDS_PER_SECOND
            + cjk_chars / cls.CJK_CHARACTERS_PER_SECOND
            + min(pauses * cls.PAUSE_SECONDS, cls.MAX_ESTIMATED_PAUSE_SECONDS)
        )
        return round(max(cls.MIN_SCENE_SECONDS, estimate), 3)

    @classmethod
    def scene_seconds(cls, scene: dict) -> float:
        """A scene that plays its own sound lasts as long as its clip; else its measured
        voiceover, else the length it asks for (`seconds`), else its narration's estimate."""
        if uses_native_audio(scene):
            clip = cls._positive(scene.get("video_seconds"))
            if clip:
                return clip
        return (
            cls._positive(scene.get("audio_seconds"))
            or min(cls._positive(scene.get("seconds")), cls.MAX_ASKED_SECONDS)
            or cls.narration_seconds(scene.get("narration"))
        )

    @staticmethod
    def _positive(value: object) -> float:
        """A positive, finite number of seconds, rounded, else 0."""
        try:
            seconds = float(str(value or 0))
        except ValueError:
            return 0.0
        return round(seconds, 3) if math.isfinite(seconds) and seconds > 0 else 0.0
