"""Supported generated-video canvases. Stored once on project input."""

from enum import StrEnum


class VideoAspectRatio(StrEnum):
    PORTRAIT = "9:16"
    LANDSCAPE = "16:9"
    SQUARE = "1:1"


DIMENSIONS = {
    VideoAspectRatio.PORTRAIT: (1080, 1920),
    VideoAspectRatio.LANDSCAPE: (1920, 1080),
    VideoAspectRatio.SQUARE: (1080, 1080),
}


def normalize(value: object) -> str:
    """Persist only supported aspect ratios; legacy projects remain portrait."""
    try:
        return VideoAspectRatio(str(value or VideoAspectRatio.PORTRAIT)).value
    except ValueError:
        return VideoAspectRatio.PORTRAIT.value


def project_aspect(record: dict) -> str:
    return normalize((record.get("input") or {}).get("aspect_ratio"))


def dimensions(value: object) -> tuple[int, int]:
    return DIMENSIONS[VideoAspectRatio(normalize(value))]


PROMPT_LABELS = {
    VideoAspectRatio.PORTRAIT: "vertical 9:16 short-form video",
    VideoAspectRatio.LANDSCAPE: "widescreen 16:9 standard video",
    VideoAspectRatio.SQUARE: "square 1:1 feed video",
}


def prompt_label(value: object) -> str:
    return PROMPT_LABELS[VideoAspectRatio(normalize(value))]
