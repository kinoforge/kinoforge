from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from kinoforge.segments.flow.nodes.base import NodeConfig, NodeGroup, NodeSpec
from kinoforge.segments.flow.ports import Port, PortType


class SaveConfig(NodeConfig):
    title: str = Field(default="", max_length=120, title="Name")


class Save(NodeSpec):
    type = "output.save"
    group = NodeGroup.OUTPUT
    label = "Result"
    description = "Keeps what reaches it as the flow's result and shows it beside the canvas."
    inputs = (
        Port("video", "Video", PortType.VIDEO),
        Port("image", "Image", PortType.IMAGE),
        Port("audio", "Audio", PortType.AUDIO),
        Port("text", "Text", PortType.TEXT),
    )
    config = SaveConfig
    host = True
    one_of = ("video", "image", "audio", "text")
    most = 4


class Privacy(StrEnum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class PublishConfig(NodeConfig):
    account: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", title="Account",
        json_schema_extra={"widget": "account"},
    )
    title: str = Field(min_length=1, max_length=100, title="Title")
    description: str = Field(
        default="", max_length=5000, title="Description", json_schema_extra={"widget": "textarea"}
    )
    privacy: Privacy = Field(default=Privacy.PRIVATE, title="Visibility")


class Publish(NodeSpec):
    type = "output.publish"
    group = NodeGroup.OUTPUT
    label = "Publish"
    description = "Uploads the video to a connected social account."
    inputs = (Port("video", "Video", PortType.VIDEO, required=True),)
    config = PublishConfig
    host = True
    most = 2
