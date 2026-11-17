import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from kinoforge.contract import AITask, ModelRef
from kinoforge.definitions.models import DefinitionError
from kinoforge.observ import with_context
from kinoforge.segments.animated.check import BoardCheck, Repair
from kinoforge.segments.common.ports import TextPorts
from kinoforge.segments.common.text import clean_text


@dataclass(frozen=True)
class Want:
    word: str
    stands_for: str


@dataclass(frozen=True)
class Drawing:
    want: Want
    shape: dict | None
    error: str = ""
    answer: object = None


class ElementDrawer:
    WORKERS = 4
    TEMPERATURE = 0.3
    MOST = 12
    WORD = 60
    NAME = "drawing"

    def __init__(self, ports: TextPorts, form: Mapping, prompt: str) -> None:
        self.ports = ports
        self.prompt = prompt
        self.schema = dict(form.get("schema") or {})
        self.total = int((form.get("limits") or {}).get("total") or 0)
        self.repair = Repair(ports, self.NAME)

    def draw(
        self,
        wants: list,
        topic: str,
        route: ModelRef | None,
        max_tokens: int,
        tries: int = BoardCheck.TRIES,
    ) -> dict:
        asked = self._wants(wants)
        if not asked:
            return {"ok": False, "error": "no pictures to draw"}
        if not self.schema:
            return {"ok": False, "error": "the animated kit has no element format"}
        try:
            system = self.ports.prompt(
                self.prompt, format=json.dumps(self.schema, ensure_ascii=False)
            )
        except DefinitionError:
            return {"ok": False, "error": "the drawing prompt is missing"}
        check = BoardCheck(self.schema, self.NAME)
        topic = clean_text(topic)
        with ThreadPoolExecutor(max_workers=min(self.WORKERS, len(asked))) as pool:
            jobs = [
                pool.submit(
                    with_context(self._one), system, topic, want, check, route, max_tokens, tries
                )
                for want in asked
            ]
            done = [job.result() for job in jobs]
        elements = [{"word": d.want.word, "shape": d.shape} for d in done if d.shape is not None]
        errors = [
            {"word": d.want.word, "error": d.error, **BoardCheck.refused(d.answer)}
            for d in done
            if d.shape is None
        ]
        if not elements:
            first = errors[0]["error"]
            return {"ok": False, "error": f"no picture could be drawn: {first}", "errors": errors}
        return {"ok": True, "elements": elements, "errors": errors}

    def _one(
        self,
        system: str,
        topic: str,
        want: Want,
        check: BoardCheck,
        route: ModelRef | None,
        max_tokens: int,
        tries: int,
    ) -> Drawing:
        brief = json.dumps(
            {"picture": want.word, "stands_for": want.stands_for, "topic": topic},
            ensure_ascii=False,
        )
        drawn: object = None
        problems: list[str] = []
        for attempt in range(max(1, tries)):
            prompt = brief if attempt == 0 else self.repair.again(brief, drawn, problems)
            try:
                answer = self.ports.complete_json(
                    AITask.STORY_ELEMENT,
                    system,
                    prompt,
                    route=route or ModelRef(),
                    temperature=self.TEMPERATURE,
                    max_tokens=max_tokens,
                )
            except json.JSONDecodeError as error:
                drawn, problems = None, Repair.unread(error)
                continue
            except Exception as error:
                return Drawing(want, None, f"the drawing model failed: {error}")
            drawn = answer.get("shape", answer) if isinstance(answer, dict) else answer
            problems = check.problems(drawn) or self._size(drawn)
            if not problems and isinstance(drawn, dict):
                return Drawing(want, drawn)
        refused = problems[0] if problems else "not an object"
        return Drawing(want, None, f"the drawing was refused: {refused}", drawn)

    def _size(self, drawn: object) -> list[str]:
        parts = drawn.get("parts") if isinstance(drawn, dict) else None
        used = sum(len(str(part.get("d") or "")) for part in parts or [] if isinstance(part, dict))
        if self.total and used > self.total:
            return [f"drawing.parts: the paths hold {used} characters, at most {self.total}"]
        return []

    @classmethod
    def _wants(cls, wants: list) -> list[Want]:
        out: dict[str, Want] = {}
        for item in wants:
            if not isinstance(item, Mapping):
                continue
            word = clean_text(item.get("word"))[: cls.WORD].strip()
            if word and word.lower() not in out:
                out[word.lower()] = Want(word, clean_text(item.get("for"))[: cls.WORD].strip())
        return list(out.values())[: cls.MOST]
