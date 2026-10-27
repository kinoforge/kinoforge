"""The node catalog: every node type, by its `type`."""

from __future__ import annotations

from typing import Dict, Type

from kinoforge.segments.flow.nodes.base import (
    FlowError,
    HostNeed,
    NodeContext,
    NodeGroup,
    NodeMedia,
    NodeSpec,
)
from kinoforge.segments.flow.nodes.edit import Captions, Concat, Mix, Trim
from kinoforge.segments.flow.nodes.generate import ImageGen, MusicGen, TextGen, VideoGen, VoiceGen
from kinoforge.segments.flow.nodes.inputs import AudioInput, ImageInput, TextInput, VideoInput
from kinoforge.segments.flow.nodes.output import Publish, Save
from kinoforge.segments.flow.nodes.story import Cast, Scenes, Writer

NODES: Dict[str, Type[NodeSpec]] = {
    spec.type: spec
    for spec in (
        TextInput, ImageInput, VideoInput, AudioInput,
        TextGen, ImageGen, VideoGen, VoiceGen, MusicGen,
        Writer, Scenes, Cast,
        Concat, Trim, Mix, Captions,
        Save, Publish,
    )
}

__all__ = ["NODES", "FlowError", "HostNeed", "NodeContext", "NodeGroup", "NodeMedia", "NodeSpec"]
