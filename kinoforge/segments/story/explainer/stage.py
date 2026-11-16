"""An explainer's stage: the diagram nodes, code files, road side and map places every board of one
video uses, and the surfaces and icons they draw, written once from the whole narration so boards
drawn side by side name the same parts. Its format comes from the caller's kit; a kit without a
stage, or a caller without the stage prompt, draws boards without one."""

import json
from collections.abc import Mapping

from kinoforge.contract import ModelRef
from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.agent import clean_text
from kinoforge.segments.story.explainer.check import BoardCheck, KitAsk, KitRefused
from kinoforge.segments.story.languages import language_name
from kinoforge.segments.story.ports import StoryPorts

PROMPT_KEY = "explainer_stage"


class StageWriter:
    TEMPERATURE = 0.4
    FILES = "files"

    def __init__(self, ports: StoryPorts, kit: Mapping) -> None:
        stage = kit.get("stage") or {}
        schema = stage.get("schema") or {}
        files = (schema.get("properties") or {}).get(self.FILES) or {}
        self.ports = ports
        self.catalog = str(stage.get("catalog") or "")
        self.check = BoardCheck(schema, "stage") if self.catalog else None
        self.most_files = int(files.get("maxItems") or 0)

    def write(
        self, rec: dict, route: ModelRef | None, max_tokens: int, tries: int = BoardCheck.TRIES
    ) -> dict:
        try:
            stage = self.stage(rec, route, max_tokens, tries)
        except KitRefused as error:
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
        given = self.given(rec)
        story = rec.get("story") or {}
        kept = story.get("stage")
        if isinstance(kept, dict) and not self.check.problems(self.own(kept, given)):
            return self.joined(kept, given)
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
        brief = self._brief(rec, given)
        written = KitAsk(self.ports, self.check, self.TEMPERATURE).ask(
            system, brief, route, max_tokens, tries
        )
        return self.joined(self.own(written, given), given)

    @classmethod
    def given(cls, rec: dict) -> list[dict]:
        files = (rec.get("input") or {}).get(cls.FILES)
        if not isinstance(files, list):
            return []
        return [
            {key: item[key] for key in ("id", "name", "lang", "lines") if key in item}
            for item in files
            if isinstance(item, Mapping) and item.get("id") and isinstance(item.get("lines"), list)
        ]

    @classmethod
    def own(cls, stage: dict, given: list[dict]) -> dict:
        if not given:
            return stage
        ids = {item["id"] for item in given}
        files = [
            item for item in stage.get(cls.FILES) or []
            if not (isinstance(item, Mapping) and item.get("id") in ids)
        ]
        out = {key: value for key, value in stage.items() if key != cls.FILES}
        return {**out, cls.FILES: files} if files else out

    def joined(self, stage: dict, given: list[dict]) -> dict:
        if not given:
            return stage
        room = max(0, self.most_files - len(given))
        own = list(self.own(stage, given).get(self.FILES) or [])[:room]
        return {**stage, self.FILES: [*given, *own]}

    @staticmethod
    def _brief(rec: dict, given: list[dict]) -> str:
        story = rec.get("story") or {}
        scenes = story.get("scenes") or []
        return json.dumps(
            {
                "topic": clean_text(story.get("logline")) or clean_text(story.get("title")),
                "brief": clean_text((rec.get("input") or {}).get("description")),
                "narration": [clean_text(scene.get("narration")) for scene in scenes],
                "given_files": given,
            },
            ensure_ascii=False,
        )
