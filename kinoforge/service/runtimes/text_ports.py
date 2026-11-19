"""Adapts an Infrelay text client + resolved definitions into the TextPorts a story or series
stage consumes. Series passes no fragment keys, so its contract/language_rule raise."""

from __future__ import annotations

import json
import re
from typing import Any

from kinoforge.contract import AITask, Meter, ModelRef, no_meter
from kinoforge.definitions import DefinitionRenderer
from kinoforge.definitions.models import DefinitionKind
from kinoforge.inference import InfrelayClient
from kinoforge.inference.infrelay import InfrelayError
from kinoforge.observ import active
from kinoforge.segments.common.ports import Chat, TextPorts

_TRAILING_COMMA = re.compile(r",\s*([}\]])")


class JsonRepair:
    @staticmethod
    def repair(text: str) -> str:
        out: list[str] = []
        i, n, in_str, esc = 0, len(text), False, False
        while i < n:
            ch = text[i]
            if in_str:
                out.append(ch)
                esc = not esc and ch == "\\"
                if not esc and ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                out.append(ch)
            elif ch == "/" and i + 1 < n and text[i + 1] == "/":
                end = text.find("\n", i + 2)
                i = n if end == -1 else end
                continue
            elif (ch.isalpha() or ch == "_") and JsonRepair.expects_key(out):
                j = i + 1
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                k = j
                while k < n and text[k] in " \t\r\n":
                    k += 1
                if k < n and text[k] == ":":
                    out.append(f'"{text[i:j]}"')
                    i = j
                    continue
                out.append(ch)
            else:
                out.append(ch)
            i += 1
        return _TRAILING_COMMA.sub(r"\1", "".join(out))

    @staticmethod
    def expects_key(out: list[str]) -> bool:
        for ch in reversed(out):
            if ch not in " \t\r\n":
                return ch in "{,"
        return False


class InfrelayTextPorts:
    def __init__(
        self,
        infrelay: InfrelayClient,
        renderer: DefinitionRenderer,
        *,
        budgets: dict[str, Any],
        label: str,
        meter: Meter = no_meter,
        contract_key: str | None = None,
        language_key: str | None = None,
        languages: dict[str, str] | None = None,
    ) -> None:
        self._infrelay = infrelay
        self._renderer = renderer
        self._budgets = budgets
        self._label = label  # "story" / "series", for the logs
        self._meter = meter
        self._contract_key = contract_key
        self._language_key = language_key
        self._languages = dict(languages or {})

    def to_ports(self) -> TextPorts:
        return TextPorts(
            complete=self.complete,
            complete_json=self.complete_json,
            parse_json=self.parse_json,
            prompt=self.prompt,
            contract=self.contract,
            language_rule=self.language_rule,
            story_budget=self.story_budget,
            meter=self._meter,
            languages=self._languages,
            open_chat=self.open_chat,
        )

    def open_chat(self, system: str) -> Chat:
        conversation = self._infrelay.open_conversation(system)
        active().debug(f"{self._label} conversation opened", conversation=conversation)

        def ask(
            task: AITask, user: str, *, route: ModelRef, temperature: float, max_tokens: int
        ) -> dict[str, Any]:
            text, _ = self._infrelay.text(
                task,
                route,
                "",
                user,
                temperature=temperature,
                max_tokens=max_tokens,
                conversation=conversation,
            )
            return self.parse_json(text)

        def close() -> None:
            try:
                self._infrelay.close_conversation(conversation)
            except InfrelayError as exc:
                active().warning(f"{self._label} conversation not closed", error=str(exc))

        return Chat(ask=ask, close=close)

    def complete(
        self,
        task: AITask,
        system: str,
        user: str,
        *,
        route: ModelRef,
        temperature: float,
        max_tokens: int,
        conversation: str = "",
        compact: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        active().debug(
            f"{self._label} text call: {task}",
            route=str(route),
            max_tokens=max_tokens,
            temperature=temperature,
            conversation=conversation or None,
        )
        turn = {"conversation": conversation, "compact": compact} if conversation else {}
        return self._infrelay.text(
            task, route, system, user, temperature=temperature, max_tokens=max_tokens, **turn
        )

    def complete_json(
        self,
        task: AITask,
        system: str,
        user: str,
        *,
        route: ModelRef,
        temperature: float,
        max_tokens: int,
        conversation: str = "",
        compact: bool = False,
    ) -> dict[str, Any]:
        text, _ = self.complete(
            task,
            system,
            user,
            route=route,
            temperature=temperature,
            max_tokens=max_tokens,
            conversation=conversation,
            compact=compact,
        )
        return self.parse_json(text)

    @staticmethod
    def parse_json(text: str) -> dict[str, Any]:
        """The JSON object out of a completion, whatever the model wrapped it in. Raw line
        breaks inside strings and trailing commas, two common model slips, are tolerated."""
        s = (text or "").strip()
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            s = s[start : end + 1]
        try:
            return json.loads(s, strict=False)
        except json.JSONDecodeError:
            try:
                return json.loads(_TRAILING_COMMA.sub(r"\1", s), strict=False)
            except json.JSONDecodeError:
                return json.loads(JsonRepair.repair(s), strict=False)

    def prompt(self, key: str, **params: object) -> str:
        return self._renderer.render(DefinitionKind.AGENT, key, **params)

    def contract(self, scene_count: int) -> str:
        if not self._contract_key:
            raise RuntimeError(f"contract fragment is not available in {self._label}")
        return self._renderer.render(
            DefinitionKind.FRAGMENT, self._contract_key, scene_count=scene_count
        )

    def language_rule(self, subject: str, language: str) -> str:
        if not self._language_key:
            raise RuntimeError(f"language fragment is not available in {self._label}")
        return self._renderer.render(
            DefinitionKind.FRAGMENT, self._language_key, subject=subject, language=language
        )

    def story_budget(self, stage_override: object = None) -> int:
        """A stage's own token budget, capped by the platform ceiling; 0 means no ceiling."""
        limit = int(self._budgets.get("story") or 0)
        try:
            requested = int(str(stage_override)) if stage_override not in (None, "") else 0
        except (TypeError, ValueError):
            requested = 0
        if requested <= 0:
            return limit
        return min(requested, limit) if limit > 0 else requested
