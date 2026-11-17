"""Narration languages and caption-alignment codes, for running the engine on its own.

A caller with its own language list sends each language's phrasing (config.languages),
which wins over this table.
"""

from collections.abc import Mapping
from enum import StrEnum


class NarrationLanguage(StrEnum):
    AUTO = ""
    ENGLISH = "en"
    HINDI = "hi"
    PUNJABI = "pa"
    ITALIAN = "it"
    GERMAN = "de"
    SPANISH = "es"
    FRENCH = "fr"
    PORTUGUESE = "pt"
    HINGLISH = "hinglish"
    PUNGLISH = "punglish"


# Supported narration languages: key -> (prompt phrasing, Whisper ISO code for
# caption alignment). "" = auto (match the title). Hinglish/Punglish are code-mixed
# styles, so the phrasing describes them; Whisper aligns on the base language.
LANGUAGES: dict = {
    NarrationLanguage.ENGLISH.value: ("English", "en"),
    NarrationLanguage.HINDI.value: ("Hindi", "hi"),
    NarrationLanguage.PUNJABI.value: ("Punjabi", "pa"),
    NarrationLanguage.ITALIAN.value: ("Italian", "it"),
    NarrationLanguage.GERMAN.value: ("German", "de"),
    NarrationLanguage.SPANISH.value: ("Spanish", "es"),
    NarrationLanguage.FRENCH.value: ("French", "fr"),
    NarrationLanguage.PORTUGUESE.value: ("Portuguese", "pt"),
    NarrationLanguage.HINGLISH.value: (
        "Hinglish, a natural, modern mix of Hindi and English in Roman/Latin"
        " script, as spoken by young urban Indians",
        "hi",
    ),
    NarrationLanguage.PUNGLISH.value: (
        "Punglish, a natural, modern mix of Punjabi and English in Roman/Latin"
        " script, as spoken by young urban Punjabis",
        "pa",
    ),
}


def whisper_code(language: str) -> str | None:
    """Whisper ISO code for a narration language key (None = auto-detect)."""
    entry = LANGUAGES.get((language or "").strip())
    return entry[1] if entry else None


AUTO_PHRASE = "the same language as the title"


def known_language(language: str, phrases: Mapping[str, str] | None = None) -> str | None:
    """The phrasing the writer is told for a language: the caller's, else this table's."""
    code = (language or "").strip()
    if phrases and phrases.get(code):
        return str(phrases[code])
    entry = LANGUAGES.get(code)
    return entry[0] if entry else None


def language_name(language: str, phrases: Mapping[str, str] | None = None) -> str:
    """The phrasing a language rule names, or the fallback phrase when none is set."""
    return known_language(language, phrases) or AUTO_PHRASE
