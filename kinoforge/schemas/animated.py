from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from kinoforge.schemas.common import (
    CHARGES_DESCRIPTION,
    PICK_DESCRIPTION,
    DefinitionBundleRequest,
    InferenceChargeResponse,
    LogEntryResponse,
    MeterEventResponse,
    OperationRequest,
)


class AnimatedOperation(StrEnum):
    WRITE_STAGE = "write_stage"
    DRAW_BOARDS = "draw_boards"
    DRAW_ELEMENTS = "draw_elements"
    WRITE_SET = "write_set"
    DIRECT_LINES = "direct_lines"


class AnimatedOperationRequest(OperationRequest):
    job_id: str = Field(description="Caller-owned operation identifier.")
    idempotency_key: str = Field(
        default="", description="Optional caller key correlating this run (and retries) in logs."
    )
    project_id: str = ""
    owner: str = ""
    operation: AnimatedOperation
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Operation input. write_stage takes the record and the explainer kit and returns "
            "the video's stage; draw_boards also takes scene targets and fixes ({scene index: "
            "problems}) and returns a checked board per scene; draw_elements takes wants "
            "([{word, for}]), the topic and the kit's element format ({schema, limits}) and "
            "returns a checked shape per picture; write_set takes the record, the skit kit and "
            "the presenter and returns the set; direct_lines also takes that set, draws (how "
            "many lines may draw) and per_call (lines directed per turn of one conversation, "
            "0 for one call) and returns one checked line per scene."
        ),
    )
    pick: dict[str, Any] = Field(default_factory=dict, description=PICK_DESCRIPTION)
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Resolved config: budgets ({board, element} output tokens), tries (answers a "
            "writer gets), languages and empty_words (words that name nothing)."
        ),
    )
    definitions: DefinitionBundleRequest


class AnimatedOperationResponse(BaseModel):
    result: dict[str, Any]
    meter_events: list[MeterEventResponse] = Field(default_factory=list)
    logs: list[LogEntryResponse] = Field(default_factory=list)
    inference: list[InferenceChargeResponse] = Field(
        default_factory=list, description=CHARGES_DESCRIPTION
    )
