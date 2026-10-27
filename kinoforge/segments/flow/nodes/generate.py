from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Any, Dict

from pydantic import Field

from kinoforge.contract import AITask, ImageSpec, VideoSpec
from kinoforge.segments.flow.nodes.base import (
    MediaKinds,
    ModelChoice,
    NodeConfig,
    NodeContext,
    NodeGroup,
    NodeMedia,
    NodeSpec,
    model_field,
)
from kinoforge.segments.flow.ports import Port, PortType


class Aspect(StrEnum):
    PORTRAIT = "9:16"
    LANDSCAPE = "16:9"
    SQUARE = "1:1"


class Resolution(IntEnum):
    SD = 480
    HD = 720
    FULL_HD = 1080


PROMPT = Port("prompt", "Prompt", PortType.TEXT, required=True)
MAX_REFERENCES = 5


class TextGenConfig(NodeConfig):
    system: str = Field(
        default="", max_length=4000, title="Instructions", json_schema_extra={"widget": "textarea"}
    )
    temperature: float = Field(default=0.7, ge=0, le=2, title="Temperature")
    max_tokens: int = Field(default=1000, ge=16, le=8000, title="Max tokens")
    model: ModelChoice = model_field(NodeMedia.TEXT)


class TextGen(NodeSpec):
    type = "generate.text"
    group = NodeGroup.GENERATE
    label = "Write text"
    description = "A language model answers the prompt."
    inputs = (PROMPT,)
    outputs = (Port("text", "Text", PortType.TEXT),)
    config = TextGenConfig
    media = NodeMedia.TEXT

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        text, _ = ctx.infrelay.complete(
            AITask.TEXT, config.model.ref(), inputs["prompt"], system=config.system,
            max_tokens=config.max_tokens, temperature=config.temperature,
        )
        return {"text": text.strip()}


class ImageGenConfig(NodeConfig):
    aspect_ratio: Aspect = Field(default=Aspect.PORTRAIT, title="Aspect")
    negative: str = Field(default="", max_length=2000, title="Avoid")
    seed: int = Field(default=0, ge=0, le=2**31 - 1, title="Seed (0 is random)")
    model: ModelChoice = model_field(NodeMedia.IMAGE)


class ImageGen(NodeSpec):
    type = "generate.image"
    group = NodeGroup.GENERATE
    label = "Image"
    description = "Paints the prompt, optionally from a reference image."
    inputs = (PROMPT, Port("reference", "Reference", PortType.IMAGE))
    outputs = (Port("image", "Image", PortType.IMAGE),)
    config = ImageGenConfig
    media = NodeMedia.IMAGE

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        spec = ImageSpec(
            aspect_ratio=config.aspect_ratio.value,
            seed=config.seed or None,
            negative=config.negative,
            reference=ctx.file(inputs.get("reference")),
        )
        data = ctx.infrelay.image(AITask.IMAGE, config.model.ref(), inputs["prompt"], spec)
        return {"image": ctx.write("image", data, MediaKinds.image_suffix(data))}


class VideoGenConfig(NodeConfig):
    seconds: int = Field(default=5, ge=1, le=20, title="Seconds")
    resolution: Resolution = Field(default=Resolution.HD, title="Resolution")
    aspect_ratio: Aspect = Field(default=Aspect.PORTRAIT, title="Aspect")
    music: bool = Field(default=False, title="Model's own music")
    model: ModelChoice = model_field(NodeMedia.VIDEO)


class VideoGen(NodeSpec):
    type = "generate.video"
    group = NodeGroup.GENERATE
    label = "Video"
    description = (
        "A clip from the prompt, optionally starting or ending on an image. References (up to "
        f"{MAX_REFERENCES}) keep people and places the same; the model uses as many as it takes."
    )
    inputs = (
        PROMPT,
        Port("first_frame", "First frame", PortType.IMAGE),
        Port("last_frame", "Last frame", PortType.IMAGE),
        Port("dialogue", "Spoken line", PortType.TEXT),
        Port("references", "References", PortType.IMAGE, many=True, most=MAX_REFERENCES),
    )
    outputs = (Port("video", "Video", PortType.VIDEO),)
    config = VideoGenConfig
    media = NodeMedia.VIDEO

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        spec = VideoSpec(
            seconds=config.seconds,
            resolution=int(config.resolution),
            aspect_ratio=config.aspect_ratio.value,
            image=ctx.file(inputs.get("first_frame")),
            last_frame=ctx.file(inputs.get("last_frame")),
            references=tuple(
                file for media in inputs.get("references") or [] if (file := ctx.file(media))
            ),
            dialogue=str(inputs.get("dialogue") or ""),
            music=config.music,
        )
        data = ctx.infrelay.video(AITask.VIDEO, config.model.ref(), inputs["prompt"], spec)
        return {"video": ctx.write("video", data, ".mp4")}


class VoiceConfig(NodeConfig):
    voice: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:-]*$", title="Voice")
    language: str = Field(default="", max_length=16, pattern=r"^[A-Za-z-]*$", title="Language")
    model: ModelChoice = model_field(NodeMedia.TTS)


class VoiceGen(NodeSpec):
    type = "generate.voice"
    group = NodeGroup.GENERATE
    label = "Voice"
    description = "Speaks the text."
    inputs = (Port("text", "Text", PortType.TEXT, required=True),)
    outputs = (Port("audio", "Audio", PortType.AUDIO),)
    config = VoiceConfig
    media = NodeMedia.TTS

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        data = ctx.infrelay.speech(
            AITask.AUDIO, config.model.ref(), inputs["text"], voice=config.voice,
            language=config.language,
        )
        return {"audio": ctx.write("audio", data, MediaKinds.audio_suffix(data))}


class MusicConfig(NodeConfig):
    seconds: int = Field(default=30, ge=5, le=240, title="Seconds")
    model: ModelChoice = model_field(NodeMedia.MUSIC)


class MusicGen(NodeSpec):
    type = "generate.music"
    group = NodeGroup.GENERATE
    label = "Music"
    description = "An instrumental track from the prompt."
    inputs = (PROMPT,)
    outputs = (Port("audio", "Music", PortType.AUDIO),)
    config = MusicConfig
    media = NodeMedia.MUSIC

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        data = ctx.infrelay.music(
            AITask.MUSIC, config.model.ref(), inputs["prompt"], seconds=config.seconds
        )
        return {"audio": ctx.write("audio", data, MediaKinds.audio_suffix(data))}
