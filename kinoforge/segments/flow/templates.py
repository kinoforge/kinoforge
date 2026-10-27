"""Ready flows a canvas starts from, with where each node sits."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, List, Tuple

STEP = 280


class FlowTemplate(StrEnum):
    STORY = "story"


Placed = Tuple[str, str, int, int, Dict[str, Any]]
Link = Tuple[str, str, str, str]


class FlowTemplates:
    """A story from a brief, the way the guided story makes it: written, a still and a clip
    per scene, a voice per line, cut together with the voices laid over."""

    STORY_NODES: Tuple[Placed, ...] = (
        ("brief", "input.text", 0, 1, {"text": ""}),
        ("writer", "story.write", 1, 1, {}),
        ("scenes", "story.scenes", 2, 1, {}),
        ("still", "generate.image", 3, 0, {}),
        ("clip", "generate.video", 4, 0, {}),
        ("voice", "generate.voice", 4, 2, {}),
        ("cut", "edit.concat", 5, 0, {}),
        ("sound", "edit.mix", 6, 1, {}),
        ("result", "output.save", 7, 1, {}),
    )
    STORY_LINKS: Tuple[Link, ...] = (
        ("brief", "text", "writer", "brief"),
        ("writer", "story", "scenes", "story"),
        ("scenes", "prompts", "still", "prompt"),
        ("scenes", "prompts", "clip", "prompt"),
        ("still", "image", "clip", "first_frame"),
        ("scenes", "narration", "voice", "text"),
        ("clip", "video", "cut", "videos"),
        ("cut", "video", "sound", "video"),
        ("voice", "audio", "sound", "voice"),
        ("sound", "video", "result", "video"),
    )
    GRAPHS = {FlowTemplate.STORY: (STORY_NODES, STORY_LINKS)}

    @classmethod
    def graph(cls, template: FlowTemplate) -> Dict[str, List[Dict[str, Any]]]:
        placed, links = cls.GRAPHS[template]
        return {
            "nodes": [
                {"id": node_id, "type": kind, "config": config,
                 "position": {"x": column * STEP, "y": row * STEP // 2}}
                for node_id, kind, column, row, config in placed
            ],
            "edges": [
                {"source": s, "source_port": sp, "target": t, "target_port": tp}
                for s, sp, t, tp in links
            ],
        }

    @classmethod
    def all(cls) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        return {template.value: cls.graph(template) for template in FlowTemplate}
