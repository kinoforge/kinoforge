from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from kinoforge.contract import JobKind
from kinoforge.schemas import SegmentStatus


@dataclass(frozen=True)
class Feature:
    code_name: str
    name: str
    description: str
    icon: str
    status: SegmentStatus = SegmentStatus.AVAILABLE


@dataclass(frozen=True)
class Requirement:
    type: str
    key: str
    purpose: str


@dataclass(frozen=True)
class SegmentSpec:
    kind: JobKind
    name: str
    label: str
    description: str
    icon: str
    execute_path: str
    features: Tuple[Feature, ...]
    requirements: Tuple[Requirement, ...]
    status: SegmentStatus = SegmentStatus.AVAILABLE
    parent: Optional[JobKind] = None


CATALOG: Tuple[SegmentSpec, ...] = (
    SegmentSpec(
        kind=JobKind.CLIPS,
        name="Shorts",
        label="Shorts from a long video",
        description="Find, rank, render, and format viral short-form moments from long video.",
        icon="scissors",
        execute_path="/v1/segments/clips/execute",
        features=(
            Feature("transcription", "Transcription",
                    "Create multilingual timed transcripts.", "audio-lines"),
            Feature("viral-moments", "Viral moment discovery",
                    "Find strong short-form moments using AI or offline analysis.", "scan-search"),
            Feature("moment-ranking", "Moment ranking",
                    "Score and rank moments using hook and engagement signals.",
                    "chart-no-axes-column-increasing"),
            Feature("clip-rendering", "Clip rendering",
                    "Cut selected moments into standalone video artifacts.", "film"),
            Feature("multi-format", "Multi-format output",
                    "Create portrait, landscape, and platform-ready aspect variants.",
                    "panels-top-left"),
            Feature("captions", "Caption alignment",
                    "Align canonical text to spoken word timing for accurate captions.",
                    "captions"),
        ),
        requirements=(
            Requirement("agent", "prompts.agents.moment_discovery_system",
                        "Editor role, moment rules and reply format for moment discovery."),
            Requirement("agent", "prompts.agents.moment_discovery",
                        "Discover strongest moments from full transcript."),
        ),
    ),
    SegmentSpec(
        kind=JobKind.STORY,
        name="Story",
        label="Story video generator",
        description="Generate a complete narrative video from a prompt or script.",
        icon="clapperboard",
        execute_path="/v1/segments/story/write",
        features=(
            Feature("story-writing", "Story writing",
                    "Turn an idea or script into a structured narrative.", "pen-line"),
            Feature("scene-planning", "Scene planning",
                    "Break stories into directed scenes with narration and visual prompts.",
                    "layout-list"),
            Feature("character-consistency", "Character consistency",
                    "Maintain reusable character identity across generated scenes.", "users"),
            Feature("media-generation", "Scene media generation",
                    "Generate images, video and voiceover for each scene.",
                    "wand-sparkles"),
            Feature("video-assembly", "Video assembly",
                    "Assemble scenes, narration, captions, and transitions.",
                    "clapperboard", SegmentStatus.PLANNED),
        ),
        requirements=(
            Requirement("agent", "story_system", "Provide fallback screenwriter persona."),
            Requirement("agent", "story_idea", "Turn project brief into screenwriter input."),
            Requirement("fragment", "prompts.fragments.contract",
                        "Define structured story output contract."),
            Requirement("fragment", "prompts.fragments.language",
                        "Apply requested narration language."),
        ),
    ),
    SegmentSpec(
        kind=JobKind.ANIMATED,
        name="Animated",
        label="Animated video generator",
        description="Stage a written script as drawn boards or a stick figure skit.",
        icon="shapes",
        execute_path="/v1/segments/animated/operate",
        features=(
            Feature("explainer", "Explainer boards",
                    "Draw each scene as cards, charts, diagrams, code, roads and maps.",
                    "presentation"),
            Feature("skit", "Stick figure skit",
                    "Cast a set and direct poses, reactions, moves and a running card.",
                    "users-round"),
            Feature("drawn-pictures", "Drawn pictures",
                    "Draw the pictures a stage names that the caller's library lacks.",
                    "pen-tool"),
            Feature("checked-answers", "Checked answers",
                    "Send a writer's answer back with what was wrong until it fits the kit.",
                    "list-checks"),
        ),
        requirements=(
            Requirement("agent", "animated_stage", "Write what every board of a video shares."),
            Requirement("agent", "animated_board", "Write one board per scene."),
            Requirement("agent", "animated_surface_diagram", "How diagram pieces are used."),
            Requirement("agent", "animated_surface_code", "How code pieces are used."),
            Requirement("agent", "animated_surface_road", "How road pieces are used."),
            Requirement("agent", "animated_surface_map", "How map pieces are used."),
            Requirement("agent", "animated_element", "Draw one picture as paths."),
            Requirement("agent", "animated_set", "Cast and dress a skit's set."),
            Requirement("agent", "animated_lines", "Direct a skit line by line."),
            Requirement("agent", "animated_repair", "Send a refused answer back to its writer."),
            Requirement("agent", "animated_repair_turn",
                        "Send a refused answer back inside a conversation."),
            Requirement("fragment", "prompts.fragments.language",
                        "Apply requested on-screen text language."),
        ),
    ),
    SegmentSpec(
        kind=JobKind.SERIES,
        name="Series",
        label="Series generator",
        description="Create recurring characters and connected multi-episode videos.",
        icon="list-video",
        execute_path="/v1/segments/series/plan",
        parent=JobKind.STORY,
        features=(
            Feature("series-planning", "Series planning",
                    "Define a reusable premise, visual identity, and episode structure.",
                    "notebook-tabs"),
            Feature("recurring-cast", "Recurring cast",
                    "Reuse character identity and personality across episodes.", "contact-round"),
            Feature("episode-planning", "Episode planning",
                    "Generate connected episode ideas from the series premise.", "list-video"),
            Feature("continuity", "Series continuity",
                    "Carry story, character, and visual context between episodes.", "git-branch"),
            Feature("episode-generation", "Episode generation",
                    "Generate each episode through the story and media pipeline.", "play-square"),
        ),
        requirements=(
            Requirement("agent", "episode_plan",
                        "Propose connected episode ideas from the series premise."),
            Requirement("agent", "story_system",
                        "Provide fallback screenwriter persona for planning."),
        ),
    ),
)


def spec_for(kind: JobKind) -> SegmentSpec:
    return next(spec for spec in CATALOG if spec.kind is kind)
