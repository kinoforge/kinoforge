from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Dict, List, Optional, Set, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kinoforge.segments.flow.nodes import NODES, NodeSpec

NODE_ID = r"^[A-Za-z0-9_-]{1,40}$"
PORT_NAME = r"^[a-z_]{1,40}$"
MAX_NODES = 80
MAX_EDGES = 200


class FlowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=NODE_ID)
    type: str = Field(min_length=1, max_length=64)
    config: Dict[str, Any] = Field(default_factory=dict)
    # The block (a scene) this node sits in.
    parent: Optional[str] = Field(default=None, pattern=NODE_ID)


class FlowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=NODE_ID)
    source_port: str = Field(pattern=PORT_NAME)
    target: str = Field(pattern=NODE_ID)
    target_port: str = Field(pattern=PORT_NAME)


class FlowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: List[FlowNode] = Field(default_factory=list, max_length=MAX_NODES)
    edges: List[FlowEdge] = Field(default_factory=list, max_length=MAX_EDGES)
    # The caller's own cap per node type, in place of the type's `most`.
    limits: Dict[str, Annotated[int, Field(ge=1, le=MAX_NODES)]] = Field(
        default_factory=dict, max_length=len(NODES)
    )


class IssueCode(StrEnum):
    EMPTY = "empty"
    DUPLICATE_NODE = "duplicate_node"
    UNKNOWN_TYPE = "unknown_type"
    TOO_MANY = "too_many"
    BAD_CONFIG = "bad_config"
    UNKNOWN_NODE = "unknown_node"
    UNKNOWN_PORT = "unknown_port"
    TYPE_MISMATCH = "type_mismatch"
    SELF_LOOP = "self_loop"
    DUPLICATE_EDGE = "duplicate_edge"
    PORT_TAKEN = "port_taken"
    MISSING_INPUT = "missing_input"
    TOO_MANY_INPUTS = "too_many_inputs"
    CYCLE = "cycle"
    BAD_PARENT = "bad_parent"
    CROSS_BLOCK = "cross_block"
    BLOCK_FULL = "block_full"
    BLOCK_LIST = "block_list"


@dataclass(frozen=True)
class Issue:
    code: IssueCode
    message: str
    node: str = ""
    edge: int = -1
    field: str = ""

    def describe(self) -> dict:
        return {"code": self.code.value, "message": self.message, "node": self.node,
                "edge": self.edge, "field": self.field}


@dataclass
class FlowCheck:
    """The graph's problems; when there are none, the order its nodes run in, the nodes that
    run once per item of a list, and the output ports that carry lists."""

    issues: List[Issue] = field(default_factory=list)
    order: List[str] = field(default_factory=list)
    mapped: List[str] = field(default_factory=list)
    lists: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def describe(self) -> dict:
        return {"ok": self.ok, "issues": [issue.describe() for issue in self.issues],
                "order": self.order, "mapped": self.mapped, "lists": self.lists}


class FlowValidator:
    def __init__(self, graph: FlowGraph) -> None:
        self._graph = graph
        self._specs: Dict[str, Type[NodeSpec]] = {}
        self._parent: Dict[str, str] = {}
        self._issues: List[Issue] = []

    def check(self) -> FlowCheck:
        if not self._graph.nodes:
            return FlowCheck(issues=[Issue(IssueCode.EMPTY, "Add a node to start.")])
        self._nodes()
        self._parents()
        incoming = self._edges()
        self._required(incoming)
        order = self._order()
        if self._issues or order is None:
            return FlowCheck(issues=self._issues)
        mapped, lists = self._lists(order, incoming)
        for node_id in mapped:
            if self._parent.get(node_id) or self._specs[node_id].block:
                self._issue(IssueCode.BLOCK_LIST, "A scene runs once: feed it one value, not a "
                            "list.", node=node_id)
        if self._issues:
            return FlowCheck(issues=self._issues)
        return FlowCheck(order=order, mapped=mapped, lists=lists)

    def _issue(self, code: IssueCode, message: str, **where: Any) -> None:
        self._issues.append(Issue(code, message, **where))

    def _nodes(self) -> None:
        count: Dict[str, int] = defaultdict(int)
        for node in self._graph.nodes:
            if node.id in self._specs:
                self._issue(IssueCode.DUPLICATE_NODE, "Two nodes share an id.", node=node.id)
                continue
            spec = NODES.get(node.type)
            if spec is None:
                self._issue(IssueCode.UNKNOWN_TYPE, f"Unknown node: {node.type}.", node=node.id)
                continue
            self._specs[node.id] = spec
            count[node.type] += 1
            most = self._graph.limits.get(node.type, spec.most)
            if count[node.type] == most + 1:
                self._issue(IssueCode.TOO_MANY, f"At most {most} {spec.label} nodes.",
                            node=node.id)
            try:
                spec.config.model_validate(node.config)
            except ValidationError as exc:
                for error in exc.errors():
                    name = ".".join(str(part) for part in error.get("loc") or ())
                    self._issue(IssueCode.BAD_CONFIG, spec.config_error(error), node=node.id,
                                field=name)

    def _parents(self) -> None:
        held: Dict[str, int] = defaultdict(int)
        for node in self._graph.nodes:
            if node.parent is None or node.id not in self._specs:
                continue
            block = self._specs.get(node.parent)
            if block is None or not block.block or self._specs[node.id].block:
                self._issue(IssueCode.BAD_PARENT, "This node cannot sit there.", node=node.id)
                continue
            self._parent[node.id] = node.parent
            held[node.parent] += 1
            if held[node.parent] == block.holds + 1:
                self._issue(IssueCode.BLOCK_FULL,
                            f"{block.label} holds at most {block.holds} nodes.", node=node.parent)

    def _crosses(self, source: str, target: str, port: str) -> bool:
        """A link that leaves its block: inside a block, links stay inside, a block is fed by
        its own nodes (and by the block before on its chain), and an outside node may feed in."""
        target_spec = self._specs[target]
        if target_spec.block:
            if port == target_spec.chain:
                return not self._specs[source].block or source in self._parent
            return self._parent.get(source) != target
        inside = self._parent.get(source)
        if inside is not None:
            return inside != self._parent.get(target)
        return self._specs[source].block and target in self._parent

    def _edges(self) -> Dict[Tuple[str, str], List[int]]:
        incoming: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        seen: Set[Tuple[str, str, str, str]] = set()
        for index, edge in enumerate(self._graph.edges):
            source, target = self._specs.get(edge.source), self._specs.get(edge.target)
            if source is None or target is None:
                self._issue(IssueCode.UNKNOWN_NODE, "A link ends at no node.", edge=index)
                continue
            out, into = source.output(edge.source_port), target.input(edge.target_port)
            if out is None or into is None:
                self._issue(IssueCode.UNKNOWN_PORT, "A link ends at no port.", edge=index,
                            node=edge.target)
                continue
            key = (edge.source, edge.source_port, edge.target, edge.target_port)
            if edge.source == edge.target:
                self._issue(IssueCode.SELF_LOOP, "A node cannot feed itself.", edge=index,
                            node=edge.target)
            elif out.type != into.type:
                self._issue(IssueCode.TYPE_MISMATCH,
                            f"{out.label} ({out.type}) cannot go into {into.label} ({into.type}).",
                            edge=index, node=edge.target)
            elif self._crosses(edge.source, edge.target, edge.target_port):
                self._issue(IssueCode.CROSS_BLOCK, "Links stay inside their scene.", edge=index,
                            node=edge.target)
            elif key in seen:
                self._issue(IssueCode.DUPLICATE_EDGE, "Two links are the same.", edge=index)
            elif not into.many and incoming[(edge.target, edge.target_port)]:
                self._issue(IssueCode.PORT_TAKEN, f"{into.label} takes one link.", edge=index,
                            node=edge.target)
            elif into.most and len(incoming[(edge.target, edge.target_port)]) >= into.most:
                self._issue(IssueCode.PORT_TAKEN, f"{into.label} takes at most {into.most}.",
                            edge=index, node=edge.target)
            else:
                seen.add(key)
                incoming[(edge.target, edge.target_port)].append(index)
        return incoming

    def _required(self, incoming: Dict[Tuple[str, str], List[int]]) -> None:
        for node_id, spec in self._specs.items():
            for port in spec.inputs:
                if port.required and not incoming.get((node_id, port.name)):
                    self._issue(IssueCode.MISSING_INPUT, f"{spec.label} needs {port.label}.",
                                node=node_id, field=port.name)
            if spec.one_of and not any(incoming.get((node_id, name)) for name in spec.one_of):
                labels = " or ".join(
                    port.label for port in spec.inputs if port.name in spec.one_of
                )
                self._issue(IssueCode.MISSING_INPUT, f"{spec.label} needs {labels}.",
                            node=node_id)
            linked = [port for port in spec.inputs
                      if port.name in spec.apart and incoming.get((node_id, port.name))]
            if len(linked) > 1:
                labels = " or ".join(port.label for port in linked)
                self._issue(IssueCode.TOO_MANY_INPUTS, f"{spec.label}: use {labels}, not both.",
                            node=node_id)

    def _order(self) -> Optional[List[str]]:
        ids = [node.id for node in self._graph.nodes if node.id in self._specs]
        after: Dict[str, Set[str]] = {node_id: set() for node_id in ids}
        waits: Dict[str, int] = dict.fromkeys(ids, 0)
        for edge in self._graph.edges:
            if edge.source in after and edge.target in waits and edge.target not in after[edge.source]:
                after[edge.source].add(edge.target)
                waits[edge.target] += 1
        ready = [node_id for node_id in ids if not waits[node_id]]
        order: List[str] = []
        while ready:
            node_id = ready.pop(0)
            order.append(node_id)
            for target in sorted(after[node_id], key=ids.index):
                waits[target] -= 1
                if not waits[target]:
                    ready.append(target)
        if len(order) < len(ids):
            stuck = next(node_id for node_id in ids if node_id not in order)
            self._issue(IssueCode.CYCLE, "Links run in a circle.", node=stuck)
            return None
        return order

    def _lists(
        self, order: List[str], incoming: Dict[Tuple[str, str], List[int]]
    ) -> Tuple[List[str], Dict[str, List[str]]]:
        lists: Dict[str, List[str]] = {}
        mapped: List[str] = []
        edges = self._graph.edges
        for node_id in order:
            spec = self._specs[node_id]
            fed = any(
                edges[index].source_port in lists.get(edges[index].source, [])
                for port in spec.inputs if not port.many
                for index in incoming.get((node_id, port.name), [])
            )
            if fed:
                mapped.append(node_id)
            carried = [port.name for port in spec.outputs if port.many or fed]
            if carried:
                lists[node_id] = carried
        return mapped, lists
