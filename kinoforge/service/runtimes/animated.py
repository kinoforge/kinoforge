from __future__ import annotations

from typing import Any, assert_never

from kinoforge.contract import JobKind, ModelRef
from kinoforge.definitions import DefinitionBundle, DefinitionRenderer
from kinoforge.inference.charges import InferenceCharges
from kinoforge.observ import bind, build_logger, logged, reset
from kinoforge.schemas import AnimatedOperation, AnimatedOperationRequest
from kinoforge.segments.animated.check import BoardCheck
from kinoforge.segments.animated.elements import ElementDrawer
from kinoforge.segments.animated.explainer.boards import BoardWriter
from kinoforge.segments.animated.explainer.stage import StageWriter
from kinoforge.segments.animated.skit.lines import LineDirector
from kinoforge.segments.animated.skit.set import SetWriter
from kinoforge.segments.common.ports import TextPorts
from kinoforge.service.meter import EventMeter
from kinoforge.service.runtimes.text_ports import InfrelayTextPorts
from kinoforge.service.settings import ServiceSettings

LANGUAGE_KEY = "prompts.fragments.language"


class AnimatedRuntime:
    def __init__(self, settings: ServiceSettings) -> None:
        self._settings = settings

    @classmethod
    def from_env(cls) -> AnimatedRuntime:
        return cls(ServiceSettings.from_env())

    @InferenceCharges.reported
    @logged
    def operate(self, request: AnimatedOperationRequest) -> dict[str, Any]:
        bundle = DefinitionBundle.from_mapping(
            request.definitions.model_dump(exclude_none=True), engine_version="0.1.0"
        )
        meter = EventMeter()
        ports = InfrelayTextPorts(
            self._settings.infrelay(request.owner),
            DefinitionRenderer(bundle),
            budgets=dict(request.config.get("budgets") or {}),
            label=JobKind.ANIMATED.value,
            meter=meter,
            language_key=LANGUAGE_KEY,
            languages={
                str(k): str(v) for k, v in (request.config.get("languages") or {}).items()
            },
        ).to_ports()
        logger = build_logger(
            job_id=request.project_id,
            segment=JobKind.ANIMATED.value,
            idempotency_key=request.idempotency_key,
            level=request.log_level,
        )
        token = bind(logger)
        try:
            result = self._dispatch(ports, request, ModelRef.from_mapping(request.pick))
        finally:
            reset(token)
        return {"result": result, "meter_events": meter.events, "logs": logger.entries}

    @classmethod
    def _dispatch(
        cls, ports: TextPorts, request: AnimatedOperationRequest, route: ModelRef
    ) -> dict[str, Any]:
        payload = request.payload
        budgets = request.config.get("budgets") or {}
        board = int(budgets.get("board") or 0)
        tries = BoardCheck.tries(request.config.get("tries"))
        record = dict(payload.get("record") or {})
        kit = dict(payload.get("kit") or {})
        match request.operation:
            case AnimatedOperation.WRITE_STAGE:
                return StageWriter(ports, kit).write(record, route, board, tries)
            case AnimatedOperation.DRAW_BOARDS:
                targets = payload.get("targets")
                return BoardWriter(ports, kit).draw(
                    record,
                    [int(i) for i in targets] if isinstance(targets, list) else None,
                    route,
                    board,
                    cls._fixes(payload.get("fixes")),
                    tries,
                )
            case AnimatedOperation.DRAW_ELEMENTS:
                wants = payload.get("wants")
                return ElementDrawer(ports, dict(payload.get("format") or {})).draw(
                    wants if isinstance(wants, list) else [],
                    str(payload.get("topic") or ""),
                    route,
                    int(budgets.get("element") or 0),
                    tries,
                )
            case AnimatedOperation.WRITE_SET:
                empty = request.config.get("empty_words")
                return SetWriter(ports, kit, empty if isinstance(empty, list) else []).write(
                    record, str(payload.get("presenter") or ""), route, board, tries
                )
            case AnimatedOperation.DIRECT_LINES:
                return LineDirector(ports, kit).direct(
                    record,
                    dict(payload.get("set") or {}),
                    str(payload.get("presenter") or ""),
                    route,
                    board,
                    cls._whole(payload.get("draws")),
                    tries,
                    cls._whole(payload.get("per_call")),
                )
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def _whole(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @staticmethod
    def _fixes(fixes: object) -> dict[int, list[str]] | None:
        if not isinstance(fixes, dict):
            return None
        return {
            int(index): [str(problem) for problem in problems][: BoardCheck.MOST]
            for index, problems in fixes.items()
            if isinstance(problems, list)
        }
