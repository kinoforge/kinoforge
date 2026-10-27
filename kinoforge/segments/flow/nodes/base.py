from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, Mapping, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field

from kinoforge.contract import MediaFile, ModelRef
from kinoforge.inference import InfrelayClient
from kinoforge.segments.flow.ports import Port
from kinoforge.service.settings import ServiceSettings


class FlowError(ValueError):
    """A node that cannot run on what it was given; its text is safe to show."""


class NodeGroup(StrEnum):
    INPUT = "input"
    GENERATE = "generate"
    STORY = "story"
    EDIT = "edit"
    OUTPUT = "output"


class NodeMedia(StrEnum):
    """The model catalog kind a node's model picker lists, and what its run is priced as."""

    TEXT = "text"
    IMAGE = "image"
    TTS = "tts"
    MUSIC = "music"
    VIDEO = "video"


class HostNeed(StrEnum):
    """What the caller resolves and sends with a node's run."""

    SCREENWRITER = "screenwriter"


class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelChoice(BaseModel):
    """A model pick; blank is the task's auto route."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="", max_length=80, pattern=r"^[A-Za-z0-9_.:/-]*$")
    model: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9_.:/@+-]*$")

    def ref(self) -> ModelRef:
        return ModelRef.from_mapping(self.model_dump())


def model_field(media: NodeMedia) -> Any:
    return Field(
        default_factory=ModelChoice,
        title="Model",
        json_schema_extra={"widget": "model", "media": media.value},
    )


_REL = re.compile(r"^[A-Za-z0-9_./-]{1,512}$")


@dataclass
class NodeContext:
    """One node run: where its media lives, the gateway it calls, and what the caller sent."""

    root: Path
    out_dir: str
    item: int
    infrelay: InfrelayClient
    host: Mapping[str, Any] = field(default_factory=dict)
    settings: Optional[ServiceSettings] = None
    is_cancelled: Callable[[], bool] = lambda: False
    # What a node ran that the caller bills besides its inference (an agent's stages), and
    # inference a runtime reported itself.
    meter_events: List[Dict[str, Any]] = field(default_factory=list)
    charges: List[Dict[str, Any]] = field(default_factory=list)

    def path(self, media: Mapping[str, Any]) -> Path:
        rel = str(media.get("path") or "")
        if not _REL.fullmatch(rel) or ".." in rel.split("/"):
            raise FlowError("a media input has an invalid path")
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise FlowError(f"media not found: {Path(rel).name}")
        return path

    def file(self, media: Optional[Mapping[str, Any]]) -> Optional[MediaFile]:
        """A media input as the gateway reads it: its link when the caller gave one."""
        if not media:
            return None
        url = str(media.get("url") or "")
        if url.startswith("https://"):
            return MediaFile(url=url)
        return MediaFile(data=self.path(media).read_bytes())

    def target(self, port: str, suffix: str) -> Path:
        directory = (self.root / self.out_dir).resolve()
        if not directory.is_relative_to(self.root):
            raise FlowError("the output folder is outside the shared root")
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{self.item}-{port}-{uuid.uuid4().hex[:8]}{suffix}"

    def media(self, path: Path) -> Dict[str, str]:
        return {"path": path.relative_to(self.root).as_posix()}

    def write(self, port: str, data: bytes, suffix: str) -> Dict[str, str]:
        path = self.target(port, suffix)
        path.write_bytes(data)
        return self.media(path)


class NodeSpec:
    """One node type: its ports, its config, and its run. `host` nodes run on the caller
    (saving to a library, publishing), never here."""

    type: ClassVar[str]
    group: ClassVar[NodeGroup]
    label: ClassVar[str]
    description: ClassVar[str]
    inputs: ClassVar[Tuple[Port, ...]] = ()
    outputs: ClassVar[Tuple[Port, ...]] = ()
    config: ClassVar[Type[NodeConfig]] = NodeConfig
    media: ClassVar[Optional[NodeMedia]] = None
    needs: ClassVar[Tuple[HostNeed, ...]] = ()
    host: ClassVar[bool] = False
    # At least one of these inputs must be connected (beyond each port's own `required`).
    one_of: ClassVar[Tuple[str, ...]] = ()
    # How many of this type one flow may hold; the caller may set its own.
    most: ClassVar[int] = 20

    @classmethod
    def input(cls, name: str) -> Optional[Port]:
        return next((port for port in cls.inputs if port.name == name), None)

    @classmethod
    def output(cls, name: str) -> Optional[Port]:
        return next((port for port in cls.outputs if port.name == name), None)

    @classmethod
    def describe(cls) -> dict:
        return {
            "type": cls.type,
            "group": cls.group.value,
            "label": cls.label,
            "description": cls.description,
            "inputs": [port.describe() for port in cls.inputs],
            "outputs": [port.describe() for port in cls.outputs],
            "config": cls.config.model_json_schema(),
            "media": cls.media.value if cls.media else None,
            "needs": [need.value for need in cls.needs],
            "host": cls.host,
            "one_of": list(cls.one_of),
            "most": cls.most,
        }

    @classmethod
    def config_error(cls, error: Mapping[str, Any]) -> str:
        """A config check's error as the user reads it, named by its field's title."""
        loc = [str(part) for part in error.get("loc") or ()]
        field_info = cls.config.model_fields.get(loc[0]) if loc else None
        title = field_info.title if field_info and field_info.title else ""
        return f"{cls.label}: {f'{title}: ' if title else ''}{error.get('msg')}."

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        raise FlowError(f"{self.label} runs on the caller")


class MediaKinds:
    """File suffixes for what a node writes."""

    @staticmethod
    def image_suffix(data: bytes) -> str:
        if data[:3] == b"\xff\xd8\xff":
            return ".jpg"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        return ".png"

    @staticmethod
    def audio_suffix(data: bytes) -> str:
        if data[:4] == b"RIFF":
            return ".wav"
        if data[:4] == b"OggS":
            return ".ogg"
        return ".mp3"
