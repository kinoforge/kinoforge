"""Story-generation core: turn a brief into the context a story agent writes from.

A story is written by a *story agent*, a pipeline of one or more LLM stages (researcher,
writer, art-director...). The final `story_json` stage returns the structured scene
breakdown; its strict schema comes from the `contract` fragment. Stage execution lives in
`run_agent.RunAgent`.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any

from kinoforge.segments.story.formats import VideoAspectRatio, prompt_label
from kinoforge.segments.story.languages import language_name
from kinoforge.segments.story.ports import StoryPorts

# Em dash, en dash, horizontal bar: house rule is commas or periods, so every text chokepoint
# runs generated copy through strip_dashes.
_DASH_RE = re.compile(r"\s*[—–―]+\s*")


class ModelFailure:
    """A model call that failed: what failed, for the user, and its cause as `detail`, for the
    caller to log or word."""

    @staticmethod
    def of(what: str, error: object) -> dict:
        return {"ok": False, "error": f"{what} failed.", "detail": str(error)}


class AudienceMode(StrEnum):
    GENERAL = "general"
    MATURE = "mature"


def strip_dashes(text: str) -> str:
    """Replace em/en/bar dashes (with any surrounding spaces) by a comma and a space."""
    return _DASH_RE.sub(", ", text or "")


def clean_text(value: object) -> str:
    return strip_dashes(str(value or "")).strip()


@dataclass(frozen=True)
class StoryBrief:
    """What the caller asks a story agent to write. cast/premise/series_* are set for Series
    episodes so the writer reuses the show's recurring characters."""

    title: str
    description: str = ""
    scene_count: int = 8
    aspect_ratio: object = VideoAspectRatio.PORTRAIT
    language: str = ""
    genre: str = ""
    cast: list[dict] = field(default_factory=list)
    premise: str = ""
    series_name: str = ""
    series_episodes: list[dict] = field(default_factory=list)
    series_position: int = 0
    mature: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StoryBrief":
        known = {f.name for f in fields(cls)}
        return cls(**{key: val for key, val in value.items() if key in known})


class BriefText:
    SERIES_RULE = (
        "Keep everything earlier episodes made true, as the slate and the series memory say. "
        "Move the show forward and repeat no earlier beat."
    )
    CAST_RULE = (
        "Reuse the recurring cast and invent no replacement for them. Each is given as they "
        "are when this video begins: identity first, then what they wear and carry."
    )
    MATURE_RULE = (
        "Audience: adults. Mature vocabulary and intensity are allowed within platform safety."
    )

    @staticmethod
    def _line(value: object) -> str:
        return " ".join(str(value or "").split())

    @classmethod
    def _cast(cls, cast: list[dict]) -> str:
        lines = []
        for member in cast:
            wears = cls._line(member["wears"])
            said = ". ".join(
                part for part in (
                    cls._line(member["look"]),
                    f"Wears {wears}" if wears else "",
                    cls._line(member["personality"]),
                )
                if part
            )
            lines.append(f"- {member['name']}: {said}" if said else f"- {member['name']}")
        return "\n".join(lines)

    @classmethod
    def _slate(cls, episodes: list[dict], position: int) -> str:
        lines = []
        for number, episode in enumerate(episodes, start=1):
            if not isinstance(episode, dict):
                continue
            title = cls._line(episode.get("title"))
            about = cls._line(episode.get("logline") or episode.get("description"))
            line = f"{number}. {title}: {about}" if about else f"{number}. {title}"
            lines.append(f"{line} (this episode)" if number == position else line)
        return "\n".join(lines)

    @classmethod
    def of(cls, brief: StoryBrief, cast: list[dict]) -> str:
        position = max(0, int(brief.series_position or 0))
        name = cls._line(brief.series_name)
        series = name or brief.series_episodes or brief.premise
        sections = [
            ("DETAILS", (brief.description or "").strip()),
            ("GENRE", cls._line(brief.genre)),
            ("SERIES", f"{name}, episode {position}" if name and position else name),
            ("PREMISE", (brief.premise or "").strip()),
            ("RECURRING CAST", cls._cast(cast)),
            ("EPISODES", cls._slate(brief.series_episodes or [], position)),
        ]
        parts = [f"{label}:\n{text}" for label, text in sections if text]
        if series:
            parts.append(cls.SERIES_RULE)
        if cast:
            parts.append(cls.CAST_RULE)
        if brief.mature:
            parts.append(cls.MATURE_RULE)
        return "\n\n".join(parts)


class Screenwriter:
    """Context builder for a story agent, over injected ports."""

    def __init__(self, ports: StoryPorts) -> None:
        self.ports = ports

    def build_context(self, brief: StoryBrief) -> dict:
        """The runtime facts an agent writes from (independent of which agent runs)."""
        series_cast = [
            {
                "name": str(character.get("name") or "").strip(),
                "look": str(character.get("look") or "").strip(),
                "wears": str(character.get("wears") or "").strip(),
                "personality": str(character.get("personality") or "").strip(),
            }
            for character in brief.cast or []
            if str(character.get("name") or "").strip()
        ]
        return {
            "title": (brief.title or "").strip(),
            "description": (brief.description or "").strip(),
            "scene_count": max(1, int(brief.scene_count or 8)),
            "output_format": prompt_label(brief.aspect_ratio),
            "language": (brief.language or "").strip(),
            "language_rule": self.ports.language_rule(
                "logline and all narration",
                language_name(brief.language, self.ports.languages),
            ),
            "genre": (brief.genre or "").strip(),
            "premise": (brief.premise or "").strip(),
            "series_name": (brief.series_name or "").strip(),
            "series_cast": json.dumps(series_cast, ensure_ascii=False),
            "series_history": json.dumps(brief.series_episodes or [], ensure_ascii=False),
            "series_position": max(0, int(brief.series_position or 0)),
            "audience": (AudienceMode.MATURE if brief.mature else AudienceMode.GENERAL).value,
            "brief": BriefText.of(brief, series_cast),
        }
