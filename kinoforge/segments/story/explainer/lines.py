import json
from collections.abc import Mapping

from kinoforge.contract import ModelRef
from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.agent import clean_text
from kinoforge.segments.story.explainer.check import BoardCheck, KitAsk, KitRefused
from kinoforge.segments.story.explainer.set import CAST
from kinoforge.segments.story.languages import language_name
from kinoforge.segments.story.ports import StoryPorts

PROMPT_KEY = "explainer_lines"


class LineDirector:
    TEMPERATURE = 0.5
    OFF = "off"
    HOME = "center"
    MOST_ACTS = 4

    def __init__(self, ports: StoryPorts, kit: Mapping) -> None:
        part = kit.get("direction") or {}
        self.ports = ports
        self.catalog = str(part.get("catalog") or "")
        self.schema = part.get("schema") or {}
        self.ref = str(kit.get("ref") or "")
        self.draws = [str(draw) for draw in kit.get("draws") or []]

    def direct(
        self,
        rec: dict,
        drawn_set: Mapping,
        presenter: str,
        route: ModelRef | None,
        max_tokens: int,
        draws: int,
        tries: int = BoardCheck.TRIES,
    ) -> dict:
        if not self.catalog:
            return {"ok": False, "error": "the skit kit is missing"}
        cast = [member for member in drawn_set.get("cast") or [] if isinstance(member, Mapping)]
        if not cast:
            return {"ok": False, "error": "the set has no cast"}
        story = rec.get("story") or {}
        scenes = [scene for scene in story.get("scenes") or [] if isinstance(scene, Mapping)]
        speakers = [self.speaker(scene, cast) for scene in scenes]
        language = str((rec.get("input") or {}).get("language") or "")
        try:
            system = self.ports.prompt(
                PROMPT_KEY,
                catalog=self.catalog,
                language_rule=self.ports.language_rule(
                    "card text", language_name(language, self.ports.languages)
                ),
            )
        except DefinitionError:
            return {"ok": False, "error": "the lines prompt is missing"}
        check = BoardCheck(self.schema, "direction", stage=drawn_set, ref=self.ref)
        brief = json.dumps(
            {
                "topic": clean_text(story.get("logline")) or clean_text(story.get("title")),
                "brief": clean_text((rec.get("input") or {}).get("description")),
                "presenter": presenter,
                "draws": self.rule(presenter, draws),
                "set": drawn_set,
                "script": [
                    {
                        "line": i + 1,
                        "speaker": speakers[i],
                        "text": clean_text(scene.get("narration")),
                    }
                    for i, scene in enumerate(scenes)
                ],
            },
            ensure_ascii=False,
        )
        errors: list[str] = []
        try:
            answer: object = KitAsk(self.ports, check, self.TEMPERATURE).ask(
                system, brief, route, max_tokens, tries
            )
        except KitRefused as error:
            answer = error.answer
            errors.append(str(error))
        given = answer.get("lines") if isinstance(answer, Mapping) else None
        if not isinstance(given, list):
            return {
                "ok": False,
                "error": errors[0] if errors else "no lines came back",
                **BoardCheck.refused(answer),
            }
        kept: dict[int, dict] = {}
        for item in given:
            number = item.get("line") if isinstance(item, Mapping) else None
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or not 1 <= number <= len(scenes)
            ):
                continue
            if problems := check.problems({"lines": [item]}):
                errors.append(f"line {number}: {problems[0]}")
                continue
            kept.setdefault(number, {key: value for key, value in item.items() if key != "line"})
        lines = [{**kept.get(i + 1, {}), "speaker": speakers[i]} for i in range(len(scenes))]
        lines = self.staged(self.capped(lines, presenter, draws), drawn_set)
        return {"ok": True, "lines": lines, "errors": errors}

    @classmethod
    def staged(cls, lines: list[dict], drawn_set: Mapping) -> list[dict]:
        cast = [member for member in drawn_set.get("cast") or [] if isinstance(member, Mapping)]
        homes = {str(member.get("id")): str(member.get("place") or cls.HOME) for member in cast}
        off = {str(member.get("id")) for member in cast if member.get("enters")}
        for line in lines:
            acts = [dict(act) for act in line.get("acts") or [] if isinstance(act, Mapping)]
            speaker = line["speaker"]
            own = next((act for act in acts if act.get("who") == speaker), None)
            if speaker in off and not (own or {}).get("move"):
                if own is None:
                    own = {"who": speaker}
                    acts = [own, *acts][: cls.MOST_ACTS]
                own["move"] = homes.get(speaker, cls.HOME)
            for act in acts:
                if act.get("move") == cls.OFF:
                    off.add(str(act.get("who")))
                elif act.get("move"):
                    off.discard(str(act.get("who")))
            if acts:
                line["acts"] = acts
        return lines

    def capped(self, lines: list[dict], presenter: str, draws: int) -> list[dict]:
        left = max(0, draws)
        for i, line in enumerate(lines):
            if line.get("to") == line["speaker"]:
                line.pop("to")
            if presenter != CAST:
                if self.draws and line.get("draw") not in self.draws:
                    line["draw"] = self.draws[0]
                continue
            if "draw" not in line:
                continue
            if i == 0 or not left:
                line.pop("draw")
                continue
            left -= 1
        return lines

    @staticmethod
    def rule(presenter: str, draws: int) -> str:
        if presenter != CAST:
            return "every line draws"
        if draws <= 0:
            return "no line draws"
        return f"at most {draws} lines draw, never the first"

    @staticmethod
    def speaker(scene: Mapping, cast: list[Mapping]) -> str:
        name = clean_text(scene.get("speaker")).casefold()
        for member in cast:
            if name and clean_text(member.get("name")).casefold() == name:
                return str(member.get("id") or "")
        return str(cast[0].get("id") or "")
