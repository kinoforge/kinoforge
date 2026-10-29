"""A writer's answer against the kit's JSON schema: the problems a writer can fix, by where
they are, and the prompt that sends them back."""

import json
from collections.abc import Iterable, Mapping

from jsonschema import Draft202012Validator, ValidationError


class BoardCheck:
    def __init__(self, schema: Mapping, name: str = "board") -> None:
        self._validator = Draft202012Validator(dict(schema))
        self.name = name

    def problems(self, answer: object, limit: int = 8) -> list[str]:
        found = self._validator.iter_errors(answer)
        errors = [inner for error in found for inner in self._inside(error)]
        errors.sort(key=lambda error: [str(part) for part in error.absolute_path])
        return [f"{self._where(error.absolute_path)}: {error.message}" for error in errors[:limit]]

    @staticmethod
    def _inside(error: ValidationError) -> list[ValidationError]:
        """A piece that fits none of the kinds says only that; the errors of the kind its `type`
        names are the ones its writer can fix."""
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
        return named[0] if len(named) == 1 else [error]

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
