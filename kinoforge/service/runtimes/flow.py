"""Flow runtime: the catalog, the graph check, and one node's run on the shared volume."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from pydantic import ValidationError

from kinoforge.inference.charges import InferenceCharges
from kinoforge.observ import logged
from kinoforge.schemas.flow import FlowNodeRunRequest
from kinoforge.segments.flow.graph import FlowGraph, FlowValidator
from kinoforge.segments.flow.nodes import NODES, FlowError, NodeContext, NodeGroup, NodeSpec
from kinoforge.segments.flow.ports import MEDIA_TYPES, Port, PortType
from kinoforge.segments.flow.templates import FlowTemplates
from kinoforge.service.executions import executions
from kinoforge.service.settings import ServiceSettings

MAX_TEXT = 20000
MAX_ITEMS = 100


class FlowValues:
    """Checks what reaches a node's input ports."""

    @classmethod
    def checked(cls, spec: type[NodeSpec], inputs: Mapping[str, Any]) -> Dict[str, Any]:
        unknown = set(inputs) - {port.name for port in spec.inputs}
        if unknown:
            raise FlowError(f"{spec.label} has no input {sorted(unknown)[0]}")
        out: Dict[str, Any] = {}
        for port in spec.inputs:
            value = inputs.get(port.name)
            if value is None or value == []:
                if port.required:
                    raise FlowError(f"{spec.label} needs {port.label}")
                continue
            if port.many:
                most = port.most or MAX_ITEMS
                if not isinstance(value, list) or len(value) > most:
                    raise FlowError(f"{port.label} takes at most {most}")
                out[port.name] = [cls._one(port, item) for item in value]
            else:
                out[port.name] = cls._one(port, value)
        return out

    @staticmethod
    def _one(port: Port, value: Any) -> Any:
        if port.type == PortType.TEXT:
            if not isinstance(value, str) or len(value) > MAX_TEXT:
                raise FlowError(f"{port.label} must be text of at most {MAX_TEXT} characters")
            if port.required and not value.strip():
                raise FlowError(f"{port.label} is empty")
            return value
        if port.type == PortType.STORY:
            if not isinstance(value, dict):
                raise FlowError(f"{port.label} must be a story")
            return value
        if port.type in MEDIA_TYPES and isinstance(value, dict) and value.get("path"):
            return {"path": str(value["path"]), "url": str(value.get("url") or "")}
        raise FlowError(f"{port.label} must be a {port.type.value} file")


class FlowRuntime:
    def __init__(self, settings: ServiceSettings) -> None:
        self._settings = settings

    @classmethod
    def from_env(cls) -> FlowRuntime:
        return cls(ServiceSettings.from_env())

    @staticmethod
    def catalog() -> Dict[str, Any]:
        return {
            "nodes": [spec.describe() for spec in NODES.values()],
            "port_types": [kind.value for kind in PortType],
            "groups": [group.value for group in NodeGroup],
            "templates": FlowTemplates.all(),
        }

    @staticmethod
    def check(graph: FlowGraph) -> Dict[str, Any]:
        return FlowValidator(graph).check().describe()

    @logged
    def run(self, request: FlowNodeRunRequest) -> Dict[str, Any]:
        spec = NODES.get(request.node.type)
        if spec is None:
            raise FlowError(f"unknown node: {request.node.type}")
        if spec.host:
            raise FlowError(f"{spec.label} runs on the caller")
        try:
            config = spec.config.model_validate(request.node.config)
        except ValidationError as exc:
            raise FlowError(spec.config_error(exc.errors()[0])) from exc
        inputs = FlowValues.checked(spec, request.inputs)
        with executions.running(f"{request.run_id}-{request.node.id}-{request.item}") as control:
            ctx = NodeContext(
                root=self._settings.shared_root.resolve(),
                out_dir=request.out_dir,
                item=request.item,
                infrelay=self._settings.infrelay(request.owner),
                host=request.host,
                settings=self._settings,
                is_cancelled=control.is_cancelled,
            )
            with InferenceCharges.collect() as charges:
                outputs = spec().run(ctx, inputs, config)
        return {
            "outputs": outputs,
            "meter_events": ctx.meter_events,
            "inference": [*charges, *ctx.charges],
        }
