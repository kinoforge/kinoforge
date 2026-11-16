import json
from collections.abc import Mapping

from kinoforge.contract import ModelRef
from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.agent import clean_text
from kinoforge.segments.story.explainer.check import BoardCheck, KitAsk, KitRefused
from kinoforge.segments.story.languages import language_name
from kinoforge.segments.story.ports import StoryPorts

PROMPT_KEY = "explainer_set"
CAST = "cast"


class SetWriter:
    TEMPERATURE = 0.5

    def __init__(self, ports: StoryPorts, kit: Mapping) -> None:
        part = kit.get("set") or {}
        self.ports = ports
        self.catalog = str(part.get("catalog") or "")
        self.check = BoardCheck(part.get("schema") or {}, "set") if self.catalog else None

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
            and not self.missing(kept, story, presenter)
        ):
            return {"ok": True, "set": kept}
        language = str((rec.get("input") or {}).get("language") or "")
        try:
            system = self.ports.prompt(
                PROMPT_KEY,
                catalog=self.catalog,
                language_rule=self.ports.language_rule(
                    "roles and card text", language_name(language, self.ports.languages)
                ),
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
                lambda answer: self.missing(answer, story, presenter),
            )
        except KitRefused as error:
            return {"ok": False, "error": str(error), **BoardCheck.refused(error.answer)}
        return {"ok": True, "set": drawn}

    @staticmethod
    def missing(drawn: Mapping, story: Mapping, presenter: str) -> list[str]:
        cast = [member for member in drawn.get("cast") or [] if isinstance(member, Mapping)]
        ids = [str(member.get("id") or "") for member in cast]
        problems = []
        if len(set(ids)) != len(ids):
            problems.append("set.cast: every cast member needs an id of their own")
        if presenter != CAST:
            if len(cast) != 1:
                problems.append(f"set.cast: has {len(cast)}, the presenter alone is a cast of one")
            return problems
        names = {clean_text(member.get("name")).casefold() for member in cast}
        speakers = dict.fromkeys(
            clean_text(scene.get("speaker"))
            for scene in story.get("scenes") or []
            if isinstance(scene, Mapping) and clean_text(scene.get("speaker"))
        )
        for speaker in speakers:
            if speaker.casefold() not in names:
                problems.append(
                    f"set.cast: {speaker!r} speaks in the script; add them by that name"
                )
        return problems

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
                    {
                        "speaker": clean_text(scene.get("speaker")),
                        "text": clean_text(scene.get("narration")),
                    }
                    for scene in scenes
                ],
            },
            ensure_ascii=False,
        )
