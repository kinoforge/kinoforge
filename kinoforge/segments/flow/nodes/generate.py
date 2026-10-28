from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Any, Dict

from pydantic import Field

from kinoforge.contract import AITask, ImageSpec, VideoSpec
from kinoforge.definitions import DefinitionBundle
from kinoforge.segments.flow.nodes.base import (
    FlowError,
    HostNeed,
    MediaKinds,
    ModelChoice,
    NodeConfig,
    NodeContext,
    NodeGroup,
    NodeMedia,
    NodeSpec,
    language_field,
    model_field,
    style_field,
)
from kinoforge.segments.flow.ports import Port, PortType
from kinoforge.segments.story.languages import NarrationLanguage
from kinoforge.segments.story.media.prompt_text import LabeledPrompt
from kinoforge.service.runtimes.presets import BundleImagePresets


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
ENGINE_VERSION = "0.1.0"


class FlowStyle:
    """A node's art style: an image preset the caller sent, laid over its prompt the way
    the story engine does."""

    @staticmethod
    def _presets(ctx: NodeContext, key: str) -> BundleImagePresets:
        bundle = ctx.host.get(HostNeed.PRESETS.value)
        if not isinstance(bundle, dict):
            raise FlowError("the art style is not set up")
        return BundleImagePresets(
            DefinitionBundle.from_mapping(bundle, engine_version=ENGINE_VERSION),
            scene_key=key, portrait_key=key, negative_key=key,
        )

    @classmethod
    def image(cls, ctx: NodeContext, prompt: str, key: str) -> str:
        return cls._presets(ctx, key).image_scene(prompt, "", key=key) if key else prompt

    @classmethod
    def video(cls, ctx: NodeContext, prompt: str, key: str) -> str:
        if not key:
            return prompt
        presets = cls._presets(ctx, key)
        return LabeledPrompt([
            ("", prompt),
            ("Cinematography", presets.image_motion(prompt, "", key=key)),
            ("Style", presets.image_scene("", "", key=key)),
        ]).join()


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
    style: str = style_field()
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
    needs = (HostNeed.PRESETS,)

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        spec = ImageSpec(
            aspect_ratio=config.aspect_ratio.value,
            seed=config.seed or None,
            negative=config.negative,
            reference=ctx.file(inputs.get("reference")),
        )
        prompt = FlowStyle.image(ctx, inputs["prompt"], config.style)
        data = ctx.infrelay.image(AITask.IMAGE, config.model.ref(), prompt, spec)
        return {"image": ctx.write("image", data, MediaKinds.image_suffix(data))}


class VideoGenConfig(NodeConfig):
    retired = ("resolution",)

    style: str = style_field()
    seconds: int = Field(
        default=5, ge=1, le=20, title="Seconds",
        description="The length asked for; a model makes the nearest length it supports.",
    )
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
    needs = (HostNeed.PRESETS,)
    # Clips are made small; an upscale comes after.
    resolution = Resolution.SD

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        spec = VideoSpec(
            seconds=config.seconds,
            resolution=int(self.resolution),
            aspect_ratio=config.aspect_ratio.value,
            image=ctx.file(inputs.get("first_frame")),
            last_frame=ctx.file(inputs.get("last_frame")),
            references=tuple(
                file for media in inputs.get("references") or [] if (file := ctx.file(media))
            ),
            dialogue=str(inputs.get("dialogue") or ""),
            music=config.music,
        )
        prompt = FlowStyle.video(ctx, inputs["prompt"], config.style)
        data = ctx.infrelay.video(AITask.VIDEO, config.model.ref(), prompt, spec)
        return {"video": ctx.write("video", data, ".mp4")}


class VoiceConfig(NodeConfig):
    # The model is the voice: a voice model's list is its voices.
    retired = ("voice",)

    language: NarrationLanguage = language_field()
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
            AITask.AUDIO, config.model.ref(), inputs["text"], language=config.language.value,
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
