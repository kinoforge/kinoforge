"""A writer's answer against the kit's JSON schema: the problems a writer can fix, by where
they are, and the prompt that sends them back."""

import json
from collections.abc import Iterable, Mapping

from jsonschema import Draft202012Validator


class BoardCheck:
    def __init__(self, schema: Mapping, name: str = "board") -> None:
        self._validator = Draft202012Validator(dict(schema))
        self.name = name

    def problems(self, answer: object, limit: int = 8) -> list[str]:
        errors = sorted(self._validator.iter_errors(answer), key=lambda error: list(error.path))
        return [f"{self._where(error.path)}: {error.message}" for error in errors[:limit]]

    def repair(self, brief: str, answer: object, problems: list[str]) -> str:
        listed = "\n".join(f"- {problem}" for problem in problems)
        return (
            f"{brief}\n\nYour {self.name} was refused:\n{listed}\n\n"
            f"Your {self.name}:\n{json.dumps(answer, ensure_ascii=False)}\n\n"
            f"Return the corrected {self.name} only, as STRICT JSON."
        )

    def _where(self, path: Iterable[object]) -> str:
        parts = [f"[{part}]" if isinstance(part, int) else f".{part}" for part in path]
        return self.name + "".join(parts)
