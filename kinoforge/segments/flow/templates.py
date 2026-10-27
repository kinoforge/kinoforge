"""Ready flows a canvas starts from, with where each node sits (inside a block, from the
block's corner)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, List, Optional, Tuple

STEP = 280
ROW = 140
SCENES = 3


class FlowTemplate(StrEnum):
    STORY = "story"
    SERIES = "series"
    SCENES = "scenes"


# id, type, x, y, config, parent
Placed = Tuple[str, str, int, int, Dict[str, Any], Optional[str]]
Link = Tuple[str, str, str, str]


def _at(column: int, row: int) -> Tuple[int, int]:
    return column * STEP, row * ROW


class FlowTemplates:
    """A story from a brief, the way the guided story makes it: written, a still and a clip
    per scene, a voice per line, cut together with the voices laid over. A series writes one
    such story per episode. Scene by scene, each scene is a block you fill yourself."""

    STORY_NODES: Tuple[Placed, ...] = (
        ("brief", "input.text", *_at(0, 1), {"text": ""}, None),
        ("writer", "story.write", *_at(1, 1), {}, None),
        ("scenes", "story.scenes", *_at(2, 1), {}, None),
        ("still", "generate.image", *_at(3, 0), {}, None),
        ("clip", "generate.video", *_at(4, 0), {}, None),
        ("voice", "generate.voice", *_at(4, 2), {}, None),
        ("cut", "edit.concat", *_at(5, 0), {}, None),
        ("sound", "edit.mix", *_at(6, 1), {}, None),
        ("result", "output.save", *_at(7, 1), {}, None),
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
    # The same story, written from each episode's brief.
    SERIES_NODES: Tuple[Placed, ...] = (
        ("brief", "input.episode", *_at(0, 1), {}, None),
        *STORY_NODES[1:],
    )
    # Inside one scene block: a still then a clip from its prompt, its line spoken over it.
    SCENE_INSIDE: Tuple[Placed, ...] = (
        ("prompt", "input.text", 30, 50, {"text": ""}, None),
        ("still", "generate.image", 30 + STEP, 50, {}, None),
        ("clip", "generate.video", 30 + 2 * STEP, 50, {}, None),
        ("line", "input.text", 30, 50 + 2 * ROW, {"text": ""}, None),
        ("voice", "generate.voice", 30 + STEP, 50 + 2 * ROW, {}, None),
        ("sound", "edit.mix", 30 + 3 * STEP, 50 + ROW, {}, None),
    )
    SCENE_LINKS: Tuple[Link, ...] = (
        ("prompt", "text", "still", "prompt"),
        ("prompt", "text", "clip", "prompt"),
        ("still", "image", "clip", "first_frame"),
        ("line", "text", "voice", "text"),
        ("clip", "video", "sound", "video"),
        ("voice", "audio", "sound", "voice"),
    )
    SCENE_WIDTH = 5 * STEP

    @classmethod
    def _scenes(cls) -> Tuple[Tuple[Placed, ...], Tuple[Link, ...]]:
        placed: List[Placed] = []
        links: List[Link] = []
        for n in range(1, SCENES + 1):
            block = f"scene{n}"
            placed.append((block, "story.scene", 0, (n - 1) * 4 * ROW, {}, None))
            placed += [(f"{block}_{i}", kind, x, y, config, block)
                       for i, kind, x, y, config, _ in cls.SCENE_INSIDE]
            links += [(f"{block}_{s}", sp, f"{block}_{t}", tp) for s, sp, t, tp in cls.SCENE_LINKS]
            links.append((f"{block}_sound", "video", block, "clip"))
            if n > 1:
                links.append((f"scene{n - 1}", "film", block, "before"))
        last = f"scene{SCENES}"
        placed += [
            ("cut", "edit.concat", cls.SCENE_WIDTH + STEP // 2, 4 * ROW, {}, None),
            ("result", "output.save", cls.SCENE_WIDTH + STEP * 3 // 2, 4 * ROW, {}, None),
        ]
        links += [(last, "film", "cut", "videos"), ("cut", "video", "result", "video")]
        return tuple(placed), tuple(links)

    @classmethod
    def _parts(cls, template: FlowTemplate) -> Tuple[Tuple[Placed, ...], Tuple[Link, ...]]:
        if template == FlowTemplate.SCENES:
            return cls._scenes()
        if template == FlowTemplate.SERIES:
            return cls.SERIES_NODES, cls.STORY_LINKS
        return cls.STORY_NODES, cls.STORY_LINKS

    @classmethod
    def graph(cls, template: FlowTemplate) -> Dict[str, List[Dict[str, Any]]]:
        placed, links = cls._parts(template)
        return {
            "nodes": [
                {"id": node_id, "type": kind, "config": config, "position": {"x": x, "y": y},
                 **({"parent": parent} if parent else {})}
                for node_id, kind, x, y, config, parent in placed
            ],
            "edges": [
                {"source": s, "source_port": sp, "target": t, "target_port": tp}
                for s, sp, t, tp in links
            ],
        }

    @classmethod
    def all(cls) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        return {template.value: cls.graph(template) for template in FlowTemplate}
