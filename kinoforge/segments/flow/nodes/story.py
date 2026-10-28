from __future__ import annotations

from typing import Any, Dict

from pydantic import Field

from kinoforge.schemas import StoryWriteRequest
from kinoforge.segments.flow.nodes.base import (
    FlowError,
    HostNeed,
    ModelChoice,
    NodeConfig,
    NodeContext,
    NodeGroup,
    NodeMedia,
    NodeSpec,
    model_field,
)
from kinoforge.segments.flow.nodes.generate import Aspect
from kinoforge.segments.flow.ports import Port, PortType
from kinoforge.segments.story.formats import VideoAspectRatio
from kinoforge.service.runtimes.story import StoryRuntime
from kinoforge.service.settings import ServiceSettings

STORY = Port("story", "Story", PortType.STORY, required=True)
TITLE_CHARS = 60


class WriterConfig(NodeConfig):
    model: ModelChoice = model_field(NodeMedia.TEXT)
    scene_count: int = Field(default=6, ge=1, le=20, title="Scenes")
    aspect_ratio: VideoAspectRatio = Field(default=VideoAspectRatio.PORTRAIT, title="Aspect")
    language: str = Field(default="", max_length=16, pattern=r"^[A-Za-z-]*$", title="Language")
    genre: str = Field(default="", max_length=60, title="Genre")


class Writer(NodeSpec):
    type = "story.write"
    group = NodeGroup.STORY
    label = "Screenwriter"
    description = "Writes a story from the brief: cast, style, and a prompt and line per scene."
    inputs = (Port("brief", "Brief", PortType.TEXT, required=True),)
    outputs = (Port("story", "Story", PortType.STORY),)
    config = WriterConfig
    media = NodeMedia.TEXT
    needs = (HostNeed.SCREENWRITER,)
    most = 2

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        writer = ctx.host.get(HostNeed.SCREENWRITER.value)
        if not isinstance(writer, dict):
            raise FlowError("the screenwriter is not set up")
        brief = str(inputs["brief"]).strip()
        request = StoryWriteRequest.model_validate({
            **writer,
            "job_id": writer.get("job_id") or "flow",
            "context": {
                "title": " ".join(brief.split())[:TITLE_CHARS],
                "description": brief,
                "scene_count": config.scene_count,
                "aspect_ratio": config.aspect_ratio.value,
                "language": config.language,
                "genre": config.genre,
            },
            **({"pick": config.model.model_dump()} if config.model.model else {}),
        })
        response = StoryRuntime(ctx.settings or ServiceSettings.from_env()).write(
            request, is_cancelled=ctx.is_cancelled
        )
        ctx.meter_events.extend(response.get("meter_events") or [])
        ctx.charges.extend(response.get("inference") or [])
        result = response.get("result") or {}
        if not result.get("ok") or not isinstance(result.get("story"), dict):
            raise FlowError(str(result.get("error") or "the screenwriter wrote no story"))
        return {"story": result["story"]}


class Scene(NodeSpec):
    type = "story.scene"
    group = NodeGroup.STORY
    label = "Scene"
    description = (
        "A scene: put its nodes inside and link its clip to the scene. Chain scenes in order; "
        "the last one holds the whole film."
    )
    inputs = (
        Port("before", "Scenes before", PortType.VIDEO, many=True),
        Port("clip", "Clip", PortType.VIDEO, required=True),
    )
    outputs = (Port("film", "Film so far", PortType.VIDEO, many=True),)
    block = True
    chain = "before"
    holds = 8

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        return {"film": [*(inputs.get("before") or []), inputs["clip"]]}


class Scenes(NodeSpec):
    type = "story.scenes"
    group = NodeGroup.STORY
    label = "Scenes"
    description = "Splits a story into its scene prompts and narration lines, one per scene."
    inputs = (STORY,)
    outputs = (
        Port("prompts", "Scene prompts", PortType.TEXT, many=True),
        Port("narration", "Narration", PortType.TEXT, many=True),
        Port("title", "Title", PortType.TEXT),
    )

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        story = inputs["story"]
        scenes = [scene for scene in story.get("scenes") or [] if isinstance(scene, dict)]
        if not scenes:
            raise FlowError("the story has no scenes")
        style = str(story.get("style") or "").strip()
        return {
            "prompts": [self._prompt(scene, style) for scene in scenes],
            "narration": [str(scene.get("narration") or "").strip() for scene in scenes],
            "title": str(story.get("title") or "").strip(),
        }

    @staticmethod
    def _prompt(scene: Dict[str, Any], style: str) -> str:
        prompt = str(scene.get("prompt") or "").strip()
        return f"{prompt}. {style}" if style else prompt


class CastConfig(NodeConfig):
    aspect_ratio: Aspect = Field(default=Aspect.LANDSCAPE, title="Sheet aspect")


class Cast(NodeSpec):
    type = "story.cast"
    group = NodeGroup.STORY
    label = "Cast sheet prompt"
    description = "A character reference sheet prompt for the story's cast, to feed an Image."
    inputs = (STORY,)
    outputs = (Port("prompt", "Sheet prompt", PortType.TEXT),)
    config = CastConfig

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        story = inputs["story"]
        cast = [
            f"{c.get('name')}: {str(c.get('description') or '').strip()}"
            for c in story.get("characters") or []
            if isinstance(c, dict) and c.get("name")
        ]
        if not cast:
            raise FlowError("the story has no cast")
        style = str(story.get("style") or "").strip()
        lines = [f"Character reference sheet, {config.aspect_ratio.value}, plain background."]
        lines += [style] if style else []
        return {"prompt": " ".join(lines + cast)}
