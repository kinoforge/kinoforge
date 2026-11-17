from __future__ import annotations

from fastapi import APIRouter

from kinoforge.schemas import AnimatedOperationRequest, AnimatedOperationResponse
from kinoforge.service.operations import Operations
from kinoforge.service.runtimes import AnimatedRuntime

router = APIRouter(tags=["Animated"])


@router.post(
    "/v1/segments/animated/operate",
    summary="Stage a written script as drawn boards or a stick figure skit",
    description=(
        "Runs one stateless Animated operation from frozen definitions. Explainer mode: "
        "write_stage (what every board of the video shares), draw_elements (pictures the "
        "stage could not find) and draw_boards (a board per scene). Skit mode: write_set "
        "(the cast, their looks and the place) and direct_lines (poses, reactions, moves and "
        "card changes per line). The caller sends its render kit and persists what comes back."
    ),
    response_model=AnimatedOperationResponse,
    responses=Operations.RESPONSES,
)
def operate_animated(request: AnimatedOperationRequest):
    return Operations.answer(request, lambda: AnimatedRuntime.from_env().operate(request))
