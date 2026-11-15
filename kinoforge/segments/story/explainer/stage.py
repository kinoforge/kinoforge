"""An explainer's stage: the diagram nodes, code files, road side and map places every board of one
video uses, and the surfaces and icons they draw, written once from the whole narration so boards
drawn side by side name the same parts. Its format comes from the caller's kit; a kit without a
stage, or a caller without the stage prompt, draws boards without one."""

import json
from collections.abc import Mapping

from kinoforge.contract import AITask, ModelRef
from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.agent import clean_text
from kinoforge.segments.story.explainer.check import BoardCheck
from kinoforge.segments.story.languages import language_name
from kinoforge.segments.story.ports import StoryPorts

PROMPT_KEY = "explainer_stage"


class StageRefused(RuntimeError):
    def __init__(self, message: str, answer: object = None) -> None:
        super().__init__(message)
        self.answer = answer


class StageWriter:
    TEMPERATURE = 0.4

    def __init__(self, ports: StoryPorts, kit: Mapping) -> None:
        stage = kit.get("stage") or {}
        self.ports = ports
        self.catalog = str(stage.get("catalog") or "")
        self.check = BoardCheck(stage.get("schema") or {}, "stage") if self.catalog else None

    def write(
        self, rec: dict, route: ModelRef | None, max_tokens: int, tries: int = BoardCheck.TRIES
    ) -> dict:
        try:
            stage = self.stage(rec, route, max_tokens, tries)
        except StageRefused as error:
            return {"ok": False, "error": str(error), **BoardCheck.refused(error.answer)}
        if stage is None:
            return {"ok": False, "error": "the explainer kit or the stage prompt is missing"}
        return {"ok": True, "stage": stage}

    def stage(
        self, rec: dict, route: ModelRef | None, max_tokens: int, tries: int = BoardCheck.TRIES
    ) -> dict | None:
        """The story's stage when it still meets the kit, else a new one; None without one."""
        if self.check is None:
            return None
        story = rec.get("story") or {}
        kept = story.get("stage")
        if isinstance(kept, dict) and not self.check.problems(kept):
            return kept
        language = str((rec.get("input") or {}).get("language") or "")
        try:
            system = self.ports.prompt(
                PROMPT_KEY,
                catalog=self.catalog,
                language_rule=self.ports.language_rule(
                    "node labels", language_name(language, self.ports.languages)
                ),
            )
        except DefinitionError:
            return None
        brief = self._brief(rec)
        drawn: object = None
        problems: list[str] = []
        for attempt in range(max(1, tries)):
            prompt = brief if attempt == 0 else self.check.repair(brief, drawn, problems)
            try:
                answer = self.ports.complete_json(
                    AITask.STORY_BOARD,
                    system,
                    prompt,
                    route=route or ModelRef(),
                    temperature=self.TEMPERATURE,
                    max_tokens=max_tokens,
                )
            except json.JSONDecodeError as error:
                drawn, problems = None, [f"the answer was not valid JSON ({error})"]
                continue
            drawn = answer.get("stage", answer) if isinstance(answer, dict) else answer
            problems = self.check.problems(drawn)
            if not problems and isinstance(drawn, dict):
                return drawn
        refused = problems[0] if problems else "not an object"
        raise StageRefused(f"the stage was refused: {refused}", drawn)

    @staticmethod
    def _brief(rec: dict) -> str:
        story = rec.get("story") or {}
        scenes = story.get("scenes") or []
        return json.dumps(
            {
                "topic": clean_text(story.get("logline")) or clean_text(story.get("title")),
                "brief": clean_text((rec.get("input") or {}).get("description")),
                "narration": [clean_text(scene.get("narration")) for scene in scenes],
            },
            ensure_ascii=False,
        )
