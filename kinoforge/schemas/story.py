"""Story segment schemas: write context/request/response and the edit-operation request."""

from enum import StrEnum
from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field

from kinoforge.schemas.common import (
    CHARGES_DESCRIPTION,
    PICK_DESCRIPTION,
    DefinitionBundleRequest,
    InferenceChargeResponse,
    LogEntryResponse,
    MeterEventResponse,
    OperationRequest,
)


class StoryContextRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = Field(description="Story title the screenwriter writes from.")
    description: str = ""
    scene_count: int = Field(default=8, ge=1)
    aspect_ratio: str = "9:16"
    language: str = ""
    genre: str = ""
    cast: list[dict[str, Any]] = Field(default_factory=list)
    premise: str = ""
    series_name: str = ""
    series_episodes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Frozen ordered episode slate/history for continuity-aware screenwriters.",
    )
    series_position: int = Field(default=0, ge=0)
    mature: bool = False


class StoryWriteRequest(OperationRequest):
    job_id: str = Field(description="Caller-owned execution identifier.")
    idempotency_key: str = Field(
        default="", description="Optional caller key correlating this run (and retries) in logs."
    )
    project_id: str = Field(default="", description="Caller-owned durable project identifier.")
    owner: str = Field(default="", description="Opaque tenant or owner identifier.")
    conversation: str = Field(
        default="",
        description="Infrelay conversation the stages run as turns in; empty runs them stateless.",
    )
    context: StoryContextRequest = Field(description="What the screenwriter writes from.")
    agent: dict[str, Any] = Field(
        description="Resolved screenwriter: ordered stages, persona, per-stage model overrides.",
    )
    pick: dict[str, Any] = Field(
        default_factory=dict,
        description=f"{PICK_DESCRIPTION} Stages without their own model use it.",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Resolved output-token budgets and other runtime config.",
    )
    definitions: DefinitionBundleRequest = Field(
        description="Frozen story prompts and fragments resolved by the caller.",
    )


class StoryWriteResponse(BaseModel):
    result: dict[str, Any] = Field(
        description="Run result: {ok, story, warnings, usage} or {ok: False, error}.",
    )
    meter_events: list[MeterEventResponse] = Field(default_factory=list)
    logs: list[LogEntryResponse] = Field(default_factory=list)
    inference: List[InferenceChargeResponse] = Field(
        default_factory=list, description=CHARGES_DESCRIPTION
    )


class StoryOperation(StrEnum):
    REWRITE_SCENE = "rewrite_scene"
    REWRITE_CHARACTERS = "rewrite_characters"
    TRANSLATE = "translate"
    DIRECT_SHOTS = "direct_shots"
    DRAW_BOARDS = "draw_boards"
    WRITE_STAGE = "write_stage"
    DRAW_ELEMENTS = "draw_elements"
    WRITE_SET = "write_set"
    DIRECT_LINES = "direct_lines"
    SUGGEST_FIELD = "suggest_field"
    SUMMARIZE_EPISODE = "summarize_episode"


class StoryOperationRequest(OperationRequest):
    job_id: str = Field(description="Caller-owned operation identifier.")
    idempotency_key: str = Field(
        default="", description="Optional caller key correlating this run (and retries) in logs."
    )
    project_id: str = ""
    owner: str = ""
    operation: StoryOperation
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Operation input: project/story, scene index, language, or instructions; "
            "draw_boards also takes the explainer kit ({catalog, schema}), scene targets and "
            "fixes ({scene index: problems}) that send a drawn board back to its writer; "
            "write_stage takes the record and the kit and returns the video's stage alone; "
            "draw_elements takes wants ([{word, for}]), the topic and the kit's element format "
            "({schema, limits}) and returns a checked shape per picture; "
            "write_set takes the record, the skit kit and the presenter (stick or cast) and returns "
            "the set; direct_lines also takes that set, draws (how many lines may draw) and "
            "per_call (lines directed per turn of one conversation, 0 for one call) and returns "
            "one checked line per scene."
        ),
    )
    agent: dict[str, Any] = Field(default_factory=dict)
    pick: dict[str, Any] = Field(default_factory=dict, description=PICK_DESCRIPTION)
    config: dict[str, Any] = Field(
        default_factory=dict, description="Resolved rewrite and translation token budgets."
    )
    definitions: DefinitionBundleRequest


class StoryOperationResponse(BaseModel):
    result: dict[str, Any]
    meter_events: list[MeterEventResponse] = Field(default_factory=list)
    logs: list[LogEntryResponse] = Field(default_factory=list)
    inference: List[InferenceChargeResponse] = Field(
        default_factory=list, description=CHARGES_DESCRIPTION
    )