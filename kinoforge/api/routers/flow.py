"""Flow segment: node catalog, graph check, and one node's run."""

from __future__ import annotations

from fastapi import APIRouter

from kinoforge.schemas.flow import (
    FlowCatalogResponse,
    FlowCheckResponse,
    FlowNodeRunRequest,
    FlowNodeRunResponse,
)
from kinoforge.segments.flow.graph import FlowGraph
from kinoforge.service.runtimes.flow import FlowRuntime

router = APIRouter(tags=["Flow"])


@router.get(
    "/v1/segments/flow/nodes",
    summary="List flow node types",
    description="Every node a flow may hold: its ports, its config schema, and how it runs.",
    response_model=FlowCatalogResponse,
)
def flow_nodes() -> dict:
    return FlowRuntime.catalog()


@router.post(
    "/v1/segments/flow/check",
    summary="Check a flow graph",
    description=(
        "Checks node types and configs, links (port types, one link per single input), "
        "required inputs and cycles. A sound graph answers with its run order, the nodes that "
        "run once per list item, and the ports that carry lists."
    ),
    response_model=FlowCheckResponse,
)
def check_flow(graph: FlowGraph) -> dict:
    return FlowRuntime.check(graph)


@router.post(
    "/v1/segments/flow/run",
    summary="Run one flow node",
    description=(
        "Runs one node (one item of a mapped node) on the inputs the caller resolved and "
        "writes its media below `out_dir`. Stateless: the caller keeps outputs and bills the "
        "returned `inference` and `meter_events`. A node that cannot run answers 422."
    ),
    response_model=FlowNodeRunResponse,
)
def run_flow_node(request: FlowNodeRunRequest) -> dict:
    return FlowRuntime.from_env().run(request)
