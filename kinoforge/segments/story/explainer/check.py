"""A writer's answer against the kit's JSON schema: the problems a writer can fix, by where
they are, and the prompt that sends them back."""

import json
from collections.abc import Callable, Iterable, Mapping

from jsonschema import Draft202012Validator, ValidationError, validators

from kinoforge.contract import AITask, ModelRef
from kinoforge.segments.story.ports import Chat, StoryPorts


class StageIds:
    SHOWN = 24

    def __init__(self, stage: Mapping) -> None:
        self.ids = {
            str(part): [str(item["id"]) for item in items if isinstance(item, Mapping) and item.get("id")]
            for part, items in stage.items()
            if isinstance(items, list)
        }

    def keyword(self, validator, part, instance, schema):
        if not isinstance(instance, str):
            return
        known = self.ids.get(str(part)) or []
        if instance in known:
            return
        if not known:
            yield ValidationError(f"{instance!r} is not on the STAGE, which has no {part}: leave this piece out")
            return
        yield ValidationError(
            f"{instance!r} is not on the STAGE; use one of: {', '.join(known[: self.SHOWN])}"
        )


class BoardCheck:
    TRIES = 2

    def __init__(
        self, schema: Mapping, name: str = "board", stage: Mapping | None = None, ref: str = ""
    ) -> None:
        kind = Draft202012Validator
        if ref and isinstance(stage, Mapping):
            kind = validators.extend(Draft202012Validator, {ref: StageIds(stage).keyword})
        self._validator = kind(dict(schema))
        self.name = name

    def problems(self, answer: object, limit: int = 8) -> list[str]:
        found = self._validator.iter_errors(answer)
        errors = [inner for error in found for inner in self._inside(error)]
        errors.sort(key=lambda error: [str(part) for part in error.absolute_path])
        return [f"{self._where(error.absolute_path)}: {self._plain(error)}" for error in errors[:limit]]

    @classmethod
    def tries(cls, asked: object) -> int:
        return max(1, asked) if isinstance(asked, int) and not isinstance(asked, bool) else cls.TRIES

    @staticmethod
    def refused(answer: object) -> dict:
        return {} if answer is None else {"answer": answer}

    @staticmethod
    def _plain(error: ValidationError) -> str:
        given = error.instance
        match error.validator:
            case "minItems" if isinstance(given, list):
                swap = "; if the narration gives fewer, use another kind of piece"
                more = swap if "piece" in error.absolute_path else ""
                return f"has {len(given)}, needs at least {error.validator_value}{more}"
            case "maxItems" if isinstance(given, list):
                return f"has {len(given)}, at most {error.validator_value}"
            case "maxLength" if isinstance(given, str):
                return f"{given!r} is {len(given)} characters, at most {error.validator_value}"
            case "required":
                return f"{error.message}; add it"
            case _:
                return error.message

    @staticmethod
    def _inside(error: ValidationError) -> list[ValidationError]:
        """A piece that fits none of the kinds says only that; the errors of the kind its `type`
        names are the ones its writer can fix, and a `type` naming no kind gets the kinds listed."""
        if error.validator not in ("oneOf", "anyOf") or not error.context:
            return [error]
        kinds: dict[object, list[ValidationError]] = {}
        for sub in error.context:
            kinds.setdefault(sub.relative_schema_path[0], []).append(sub)
        named = [
            subs
            for subs in kinds.values()
            if not any(sub.validator == "const" and list(sub.path) == ["type"] for sub in subs)
        ]
        if len(named) == 1:
            return named[0]
        if not named and isinstance(error.instance, dict):
            kinds_named = sorted({str(sub.validator_value) for sub in error.context if sub.validator == "const"})
            error.message = (
                f"type {error.instance.get('type')!r} is not a piece kind; use one of: "
                + ", ".join(kinds_named)
            )
        return [error]

    def repair(self, brief: str, answer: object, problems: list[str]) -> str:
        listed = "\n".join(f"- {problem}" for problem in problems)
        return (
            f"{brief}\n\nYour {self.name} was refused:\n{listed}\n\n"
            f"Your {self.name}:\n{json.dumps(answer, ensure_ascii=False)}\n\n"
            f"Return the corrected {self.name} only, as STRICT JSON."
        )

    def follow_up(self, problems: list[str]) -> str:
        listed = "\n".join(f"- {problem}" for problem in problems)
        return (
            f"Your {self.name} was refused:\n{listed}\n\n"
            f"Return the corrected {self.name} only, as STRICT JSON."
        )

    def _where(self, path: Iterable[object]) -> str:
        parts = [f"[{part}]" if isinstance(part, int) else f".{part}" for part in path]
        return self.name + "".join(parts)


class KitRefused(RuntimeError):
    def __init__(self, message: str, answer: object = None) -> None:
        super().__init__(message)
        self.answer = answer


class KitAsk:
    def __init__(self, ports: StoryPorts, check: BoardCheck, temperature: float) -> None:
        self.ports = ports
        self.check = check
        self.temperature = temperature

    def ask(
        self,
        system: str,
        brief: str,
        route: ModelRef | None,
        max_tokens: int,
        tries: int,
        more: Callable[[dict], list[str]] = lambda _answer: [],
        chat: Chat | None = None,
    ) -> dict:
        drawn: object = None
        problems: list[str] = []
        for attempt in range(max(1, tries)):
            try:
                if chat is None:
                    prompt = brief if attempt == 0 else self.check.repair(brief, drawn, problems)
                    answer = self.ports.complete_json(
                        AITask.STORY_BOARD,
                        system,
                        prompt,
                        route=route or ModelRef(),
                        temperature=self.temperature,
                        max_tokens=max_tokens,
                    )
                else:
                    answer = chat.ask(
                        AITask.STORY_BOARD,
                        brief if attempt == 0 else self.check.follow_up(problems),
                        route=route or ModelRef(),
                        temperature=self.temperature,
                        max_tokens=max_tokens,
                    )
            except json.JSONDecodeError as error:
                drawn, problems = None, [f"the answer was not valid JSON ({error})"]
                continue
            drawn = answer.get(self.check.name, answer) if isinstance(answer, dict) else answer
            problems = self.check.problems(drawn)
            if not problems and isinstance(drawn, dict):
                problems = more(drawn)
            if not problems and isinstance(drawn, dict):
                return drawn
        refused = problems[0] if problems else "not an object"
        raise KitRefused(f"the {self.check.name} was refused: {refused}", drawn)
