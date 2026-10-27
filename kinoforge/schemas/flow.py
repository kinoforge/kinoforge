"""Flow segment schemas: the node catalog, the graph check, and one node's run."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from kinoforge.schemas.common import (
    CHARGES_DESCRIPTION,
    InferenceChargeResponse,
    LoggableRequest,
    MeterEventResponse,
)
from kinoforge.segments.flow.graph import NODE_ID, FlowNode

OUT_DIR = r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+){0,7}$"


class FlowCatalogResponse(BaseModel):
    nodes: List[Dict[str, Any]] = Field(
        description="Every node type: group, ports, JSON schema of its config, the model kind "
        "its picker lists, what the caller sends with it (`needs`), and whether it runs on the "
        "caller (`host`)."
    )
    port_types: List[str]
    groups: List[str]


class FlowCheckResponse(BaseModel):
    ok: bool
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    order: List[str] = Field(default_factory=list, description="The order nodes run in.")
    mapped: List[str] = Field(
        default_factory=list, description="Nodes that run once per item of a list input."
    )
    lists: Dict[str, List[str]] = Field(
        default_factory=dict, description="Per node, the output ports that carry lists."
    )


class FlowNodeRunRequest(LoggableRequest):
    run_id: str = Field(pattern=NODE_ID, description="Caller-owned run identifier.")
    owner: str = Field(default="", max_length=128, description="Opaque tenant identifier.")
    node: FlowNode
    item: int = Field(default=0, ge=0, le=999, description="Which item of a mapped run this is.")
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per input port its value: text, a story, or media {path, url?}; a list "
        "for a `many` port.",
    )
    out_dir: str = Field(
        pattern=OUT_DIR, description="Folder below the shared root the node writes into."
    )
    host: Dict[str, Any] = Field(
        default_factory=dict, description="What the node `needs`, resolved by the caller."
    )


class FlowNodeRunResponse(BaseModel):
    outputs: Dict[str, Any] = Field(description="Per output port its value.")
    meter_events: List[MeterEventResponse] = Field(default_factory=list)
    inference: List[InferenceChargeResponse] = Field(
        default_factory=list, description=CHARGES_DESCRIPTION
    )
