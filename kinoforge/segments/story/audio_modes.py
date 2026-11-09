"""Typed per-scene audio intent shared by generation, timing, and assembly."""

from enum import StrEnum


class SceneAudioMode(StrEnum):
    NONE = "none"
    VOICEOVER = "voiceover"
    NATIVE = "native"


def _default(scene: dict) -> SceneAudioMode:
    """Unset, a scene with words is voiced over and one without plays no sound."""
    spoken = str(scene.get("narration") or "").strip()
    return SceneAudioMode.VOICEOVER if spoken else SceneAudioMode.NONE


def mode_for(scene: dict) -> SceneAudioMode:
    try:
        return SceneAudioMode(scene.get("audio_mode") or _default(scene))
    except ValueError:
        return _default(scene)


def includes_voiceover(scene: dict) -> bool:
    return mode_for(scene) == SceneAudioMode.VOICEOVER


def uses_native_audio(scene: dict) -> bool:
    return mode_for(scene) == SceneAudioMode.NATIVE


def clear_voiceover(scene: dict) -> None:
    for field in ("audio", "audio_v", "audio_seconds", "words"):
        scene[field] = None
