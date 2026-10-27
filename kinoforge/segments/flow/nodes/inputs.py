from __future__ import annotations

from typing import Any, Dict

from pydantic import Field

from kinoforge.segments.flow.nodes.base import NodeConfig, NodeContext, NodeGroup, NodeSpec
from kinoforge.segments.flow.ports import Port, PortType

ASSET_PATTERN = r"^[A-Za-z0-9_./-]{1,512}$"


class TextConfig(NodeConfig):
    text: str = Field(
        min_length=1, max_length=10000, title="Text", json_schema_extra={"widget": "textarea"}
    )


class TextInput(NodeSpec):
    type = "input.text"
    group = NodeGroup.INPUT
    label = "Prompt"
    description = "Text you write: a prompt, a brief, a line to speak."
    outputs = (Port("text", "Text", PortType.TEXT),)
    config = TextConfig

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        return {"text": config.text.strip()}


class EpisodeInput(NodeSpec):
    type = "input.episode"
    group = NodeGroup.INPUT
    label = "Episode"
    description = "This episode's title and brief. The series sets them for each run."
    outputs = (Port("text", "Brief", PortType.TEXT), Port("title", "Title", PortType.TEXT))
    host = True
    most = 1


class AssetConfig(NodeConfig):
    asset: str = Field(
        pattern=ASSET_PATTERN, title="File", json_schema_extra={"widget": "upload"}
    )


class _Upload(NodeSpec):
    group = NodeGroup.INPUT
    config = AssetConfig

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        port = self.outputs[0].name
        return {port: ctx.media(ctx.path({"path": config.asset}))}


class ImageInput(_Upload):
    type = "input.image"
    label = "Image"
    description = "An image you upload."
    outputs = (Port("image", "Image", PortType.IMAGE),)


class VideoInput(_Upload):
    type = "input.video"
    label = "Video"
    description = "A video you upload."
    outputs = (Port("video", "Video", PortType.VIDEO),)


class AudioInput(_Upload):
    type = "input.audio"
    label = "Audio"
    description = "Audio you upload: a voice, a song."
    outputs = (Port("audio", "Audio", PortType.AUDIO),)
