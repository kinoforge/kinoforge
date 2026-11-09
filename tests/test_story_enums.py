"""Per-scene audio intent, video canvas, and narration-language tables."""

from __future__ import annotations

from kinoforge.segments.story.audio_modes import (
    SceneAudioMode,
    clear_voiceover,
    includes_voiceover,
    mode_for,
    uses_native_audio,
)
from kinoforge.segments.story.formats import (
    VideoAspectRatio,
    dimensions,
    project_aspect,
    prompt_label,
    normalize,
)
from kinoforge.segments.story.languages import language_name, whisper_code


# --- audio modes ----------------------------------------------------------

def test_mode_for_unset_is_the_voice_with_words_and_none_without():
    assert mode_for({"narration": "Hello."}) is SceneAudioMode.VOICEOVER
    assert mode_for({}) is SceneAudioMode.NONE


def test_mode_for_reads_each_choice():
    for mode in SceneAudioMode:
        assert mode_for({"narration": "Hello.", "audio_mode": mode.value}) is mode


def test_mode_for_unknown_falls_back_to_the_default():
    assert mode_for({"narration": "Hi.", "audio_mode": "surround"}) is SceneAudioMode.VOICEOVER


def test_a_scene_is_voiced_over_or_plays_its_own_sound_never_both():
    worded = {"narration": "Hi."}
    assert includes_voiceover(worded) and not uses_native_audio(worded)
    native = {**worded, "audio_mode": "native"}
    assert uses_native_audio(native) and not includes_voiceover(native)
    silent = {**worded, "audio_mode": "none"}
    assert not includes_voiceover(silent) and not uses_native_audio(silent)


def test_clear_voiceover_nulls_derived_fields():
    scene = {"audio": "a", "audio_v": 1, "audio_seconds": 3.0, "words": ["x"], "keep": "me"}
    clear_voiceover(scene)
    assert scene["audio"] is None
    assert scene["audio_v"] is None
    assert scene["audio_seconds"] is None
    assert scene["words"] is None
    assert scene["keep"] == "me"


# --- formats --------------------------------------------------------------

def test_normalize_keeps_supported_and_defaults_the_rest():
    assert normalize("16:9") == "16:9"
    assert normalize("9:16") == "9:16"
    assert normalize("4:3") == VideoAspectRatio.PORTRAIT.value
    assert normalize(None) == VideoAspectRatio.PORTRAIT.value


def test_project_aspect_reads_nested_input():
    assert project_aspect({"input": {"aspect_ratio": "16:9"}}) == "16:9"
    assert project_aspect({}) == "9:16"


def test_dimensions_map_each_ratio():
    assert dimensions("16:9") == (1920, 1080)
    assert dimensions("9:16") == (1080, 1920)


def test_prompt_label_matches_ratio():
    assert "widescreen" in prompt_label("16:9")
    assert "vertical" in prompt_label("9:16")


# --- languages ------------------------------------------------------------

def test_whisper_code_maps_language_key():
    assert whisper_code("fr") == "fr"
    assert whisper_code("hinglish") == "hi"  # code-mixed aligns on base language
    assert whisper_code("punglish") == "pa"


def test_whisper_code_none_for_auto_or_unknown():
    assert whisper_code("") is None
    assert whisper_code("zz") is None
    assert whisper_code("  ") is None


def test_language_name_returns_name_or_fallback():
    assert language_name("de") == "German"
    assert language_name("hinglish").startswith("Hinglish")
    assert language_name("") == "the same language as the title"
