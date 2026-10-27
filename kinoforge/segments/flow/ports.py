from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PortType(StrEnum):
    """What travels on an edge. Media travels as {path} below the shared root, with a {url}
    the inference service may read when the caller has one."""

    TEXT = "text"
    STORY = "story"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


MEDIA_TYPES = frozenset({PortType.IMAGE, PortType.VIDEO, PortType.AUDIO})


@dataclass(frozen=True)
class Port:
    """One input or output of a node. A `many` input takes a list (every edge into it adds
    to it); a single input fed a list runs the node once per item."""

    name: str
    label: str
    type: PortType
    required: bool = False
    many: bool = False

    def describe(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type.value,
            "required": self.required,
            "many": self.many,
        }
