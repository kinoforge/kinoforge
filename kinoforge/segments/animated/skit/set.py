import json
from collections.abc import Iterable, Mapping

from kinoforge.contract import ModelRef
from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.animated.check import BoardCheck, KitAsk, KitRefused
from kinoforge.segments.animated.prompts import FilmLanguage, KitWords
from kinoforge.segments.animated.skit.rules import CAST, SetRules
from kinoforge.segments.common.ports import TextPorts
from kinoforge.segments.common.text import clean_text


class ScriptUtils:
    @staticmethod
    def line(head: dict, scene: Mapping) -> dict:
        line = {**head, "text": clean_text(scene.get("narration"))}
        does = clean_text(scene.get("prompt"))
        return {**line, "does": does} if does else line


class SetWriter:
    TEMPERATURE = 0.5
    NAME = "set"

    def __init__(
        self, ports: TextPorts, kit: Mapping, prompt: str, empty: Iterable[object] = ()
    ) -> None:
        part = kit.get("set") or {}
        self.ports = ports
        self.prompt = prompt
        self.kit = kit
        self.format = str(part.get("format") or "")
        self.check = BoardCheck(part.get("schema") or {}, self.NAME) if self.format else None
        self.rules = SetRules(kit, empty)

    def write(
        self,
        rec: dict,
        presenter: str,
        route: ModelRef | None,
        max_tokens: int,
        tries: int = BoardCheck.TRIES,
    ) -> dict:
        if self.check is None:
            return {"ok": False, "error": "the skit kit is missing"}
        story = rec.get("story") or {}
        kept = story.get("set")
        if (
            isinstance(kept, dict)
            and not self.check.problems(kept)
            and not self.rules.problems(kept, story, presenter)
        ):
            return {"ok": True, "set": kept}
        try:
            system = self.ports.prompt(
                self.prompt,
                set_format=self.format,
                language_rule=FilmLanguage.rule(self.ports, rec, "roles and card text"),
                **KitWords.params(self.kit),
            )
        except DefinitionError:
            return {"ok": False, "error": "the set prompt is missing"}
        try:
            drawn = KitAsk(self.ports, self.check, self.TEMPERATURE).ask(
                system,
                self.brief(rec, presenter),
                route,
                max_tokens,
                tries,
                lambda answer: self.rules.problems(answer, story, presenter),
            )
        except KitRefused as error:
            return {"ok": False, "error": str(error), **BoardCheck.refused(error.answer)}
        return {"ok": True, "set": drawn}

    @staticmethod
    def brief(rec: dict, presenter: str) -> str:
        story = rec.get("story") or {}
        scenes = [scene for scene in story.get("scenes") or [] if isinstance(scene, Mapping)]
        return json.dumps(
            {
                "topic": clean_text(story.get("logline")) or clean_text(story.get("title")),
                "brief": clean_text((rec.get("input") or {}).get("description")),
                "presenter": presenter,
                "characters": [
                    {
                        "name": clean_text(person.get("name")),
                        "description": clean_text(person.get("description")),
                    }
                    for person in story.get("characters") or []
                    if isinstance(person, Mapping) and presenter == CAST
                ],
                "script": [
                    ScriptUtils.line({"speaker": clean_text(scene.get("speaker"))}, scene)
                    for scene in scenes
                ],
            },
            ensure_ascii=False,
        )
