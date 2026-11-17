import json
from collections.abc import Mapping
from functools import partial

from kinoforge.contract import ModelRef
from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.animated.check import BoardCheck, KitAsk, KitRefused
from kinoforge.segments.animated.prompts import FilmLanguage, KitWords
from kinoforge.segments.animated.skit.rules import CAST, LineRules
from kinoforge.segments.animated.skit.set import ScriptUtils
from kinoforge.segments.common.ports import TextPorts
from kinoforge.segments.common.text import clean_text


class LineDirector:
    TEMPERATURE = 0.5
    NAME = "direction"
    FILM = "\n\nTHE FILM\n"
    CHANGES = " | "

    def __init__(self, ports: TextPorts, kit: Mapping, prompt: str) -> None:
        part = kit.get("direction") or {}
        words = kit.get("words") or {}
        self.ports = ports
        self.prompt = prompt
        self.kit = kit
        self.format = str(part.get("format") or "")
        self.changes = self.CHANGES.join(str(change) for change in part.get("changes") or [])
        self.schema = part.get("schema") or {}
        self.ref = str(kit.get("ref") or "")
        self.draws = [str(draw) for draw in words.get("draws") or []]
        self.places = [str(place) for place in words.get("places") or []]
        self.words = words

    def direct(
        self,
        rec: dict,
        drawn_set: Mapping,
        presenter: str,
        route: ModelRef | None,
        max_tokens: int,
        draws: int,
        tries: int = BoardCheck.TRIES,
        per_call: int = 0,
    ) -> dict:
        if not self.format:
            return {"ok": False, "error": "the skit kit is missing"}
        cast = [member for member in drawn_set.get("cast") or [] if isinstance(member, Mapping)]
        if not cast:
            return {"ok": False, "error": "the set has no cast"}
        story = rec.get("story") or {}
        scenes = [scene for scene in story.get("scenes") or [] if isinstance(scene, Mapping)]
        speakers = [self.speaker(scene, cast) for scene in scenes]
        try:
            system = self.ports.prompt(
                self.prompt,
                direction_format=self.format,
                changes=self.changes,
                language_rule=FilmLanguage.rule(self.ports, rec, "card text"),
                **KitWords.params(self.kit),
            )
        except DefinitionError:
            return {"ok": False, "error": "the lines prompt is missing"}
        check = BoardCheck(self.schema, self.NAME, stage=drawn_set, ref=self.ref)
        rules = LineRules(drawn_set, self.places, self.words)
        film = {
            "topic": clean_text(story.get("logline")) or clean_text(story.get("title")),
            "brief": clean_text((rec.get("input") or {}).get("description")),
            "presenter": presenter,
            "draws": self.allowed(presenter, draws),
            "set": drawn_set,
            "script": [
                ScriptUtils.line({"line": i + 1, "speaker": speakers[i]}, scene)
                for i, scene in enumerate(scenes)
            ],
        }
        ask = KitAsk(self.ports, check, self.TEMPERATURE)
        errors: list[str] = []
        kept: dict[int, dict] = {}
        at = dict(rules.start)
        chunks = self.chunks(len(scenes), per_call)
        chat = (
            self.ports.open_chat(system + self.FILM + json.dumps(film, ensure_ascii=False))
            if len(chunks) > 1 and self.ports.open_chat is not None
            else None
        )
        answered = False
        answer: object = None
        try:
            for span in chunks:
                brief = (
                    json.dumps(film, ensure_ascii=False)
                    if chat is None
                    else json.dumps({"direct": {"from": span[0], "to": span[1]}})
                )
                try:
                    answer = ask.ask(
                        "" if chat else system,
                        brief,
                        route,
                        max_tokens,
                        tries,
                        partial(self.clashes, rules, speakers, dict(at), span),
                        chat,
                    )
                except KitRefused as error:
                    errors.append(str(error))
                    answer = error.answer
                answered = self.came(answer) or answered
                asked = LineRules.numbered(self.valid(answer, check, errors), span)
                for number in range(span[0], span[1] + 1):
                    _, item = asked.get(number, (-1, {}))
                    kept[number], at = rules.played(item, speakers[number - 1], at)
        finally:
            if chat is not None:
                chat.close()
        if not answered:
            return {
                "ok": False,
                "error": errors[0] if errors else "no lines came back",
                **BoardCheck.refused(answer),
            }
        lines = [{**kept.get(i + 1, {}), "speaker": speakers[i]} for i in range(len(scenes))]
        return {"ok": True, "lines": self.capped(lines, presenter, draws), "errors": errors}

    def chunks(self, count: int, per_call: int) -> list[tuple[int, int]]:
        if per_call <= 0 or count <= per_call or self.ports.open_chat is None:
            return [(1, count)]
        return [
            (first, min(count, first + per_call - 1)) for first in range(1, count + 1, per_call)
        ]

    @classmethod
    def clashes(
        cls,
        rules: LineRules,
        speakers: list[str],
        at: dict[str, str],
        span: tuple[int, int],
        answer: dict,
    ) -> list[str]:
        return rules.problems(cls.items(answer), speakers, at, span)

    @staticmethod
    def items(answer: object) -> list:
        listed = answer.get("lines") if isinstance(answer, Mapping) else None
        return listed if isinstance(listed, list) else []

    @staticmethod
    def came(answer: object) -> bool:
        return isinstance(answer, Mapping) and isinstance(answer.get("lines"), list)

    @classmethod
    def valid(cls, answer: object, check: BoardCheck, errors: list[str]) -> list:
        kept = []
        for item in cls.items(answer):
            number = item.get("line") if isinstance(item, Mapping) else None
            if not isinstance(number, int) or isinstance(number, bool):
                continue
            if problems := check.problems({"lines": [item]}):
                errors.append(f"line {number}: {problems[0]}")
                continue
            kept.append(item)
        return kept

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
    def allowed(presenter: str, draws: int) -> dict:
        if presenter != CAST:
            return {"every": True}
        return {"most": max(0, draws)}

    @staticmethod
    def speaker(scene: Mapping, cast: list[Mapping]) -> str:
        name = clean_text(scene.get("speaker")).casefold()
        for member in cast:
            if name and clean_text(member.get("name")).casefold() == name:
                return str(member.get("id") or "")
        return str(cast[0].get("id") or "")
