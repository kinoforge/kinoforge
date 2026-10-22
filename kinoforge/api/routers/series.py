"""Series segment: episode planning and recurring-cast portrait rendering."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from kinoforge.schemas import (
    ImageRenderRequest,
    ImageRenderResponse,
    SeriesPlanRequest,
    SeriesPlanResponse,
)
from kinoforge.service.operations import Operations
from kinoforge.service.runtimes import MediaRuntime, SeriesRuntime

router = APIRouter(tags=["Series"])


@router.post(
    "/v1/segments/series/plan",
    summary="Plan connected episodes for a series",
    description=(
        "Runs the resolved showrunner over a series premise and cast and returns proposed "
        "episode ideas (title + description), plus meter events and logs. Stateless: the caller "
        "persists the series and creates the episodes the user approves."
    ),
    response_model=SeriesPlanResponse,
    responses=Operations.RESPONSES,
)
def plan_series(request: SeriesPlanRequest):
    return Operations.answer(request, lambda: SeriesRuntime.from_env().plan(request))


@router.post(
    "/v1/segments/series/media/portrait",
    summary="Render one recurring cast portrait",
    description=(
        "Builds a recurring-character portrait from frozen presets and returns image bytes. "
        "Stateless: caller stores and selects portrait."
    ),
    response_model=ImageRenderResponse,
    responses=Operations.RESPONSES,
)
def render_series_portrait(request: ImageRenderRequest):
    if request.mode != "character":
        raise HTTPException(422, "Series portrait mode must be character")
    return Operations.answer(request, lambda: MediaRuntime.from_env().render_image(request))
