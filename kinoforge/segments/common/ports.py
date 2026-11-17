from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from kinoforge.contract import AITask, Meter, ModelRef, no_meter


class Complete(Protocol):
    def __call__(
        self, task: AITask, system: str, user: str, *,
        route: ModelRef, temperature: float, max_tokens: int,
        conversation: str = "", compact: bool = False,
    ) -> tuple[str, dict]: ...


class CompleteJson(Protocol):
    def __call__(
        self, task: AITask, system: str, user: str, *,
        route: ModelRef, temperature: float, max_tokens: int,
        conversation: str = "", compact: bool = False,
    ) -> dict: ...


class ParseJson(Protocol):
    def __call__(self, text: str) -> dict: ...


class Prompt(Protocol):
    def __call__(self, key: str, **params: object) -> str: ...


class Contract(Protocol):
    def __call__(self, scene_count: int) -> str: ...


class LanguageRule(Protocol):
    def __call__(self, subject: str, language: str) -> str: ...


class StoryBudget(Protocol):
    def __call__(self, stage_override: object = None) -> int: ...


class ChatTurn(Protocol):
    def __call__(
        self, task: AITask, user: str, *,
        route: ModelRef, temperature: float, max_tokens: int,
    ) -> dict: ...


@dataclass(frozen=True)
class Chat:
    ask: ChatTurn
    close: Callable[[], None]


class OpenChat(Protocol):
    def __call__(self, system: str) -> Chat: ...


@dataclass(frozen=True)
class TextPorts:
    complete: Complete
    complete_json: CompleteJson
    parse_json: ParseJson
    prompt: Prompt
    contract: Contract
    language_rule: LanguageRule
    story_budget: StoryBudget
    meter: Meter = no_meter
    # The caller's languages, code -> what the writer is told; empty uses the engine's own.
    languages: Mapping[str, str] = field(default_factory=dict)
    open_chat: OpenChat | None = None
