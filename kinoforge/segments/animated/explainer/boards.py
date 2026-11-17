import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from kinoforge.contract import AITask, ModelRef
from kinoforge.observ import with_context
from kinoforge.segments.animated.check import BoardCheck, KitRefused, Repair
from kinoforge.segments.animated.explainer.catalog import KitCatalog
from kinoforge.segments.animated.explainer.stage import StageWriter
from kinoforge.segments.animated.prompts import FilmLanguage
from kinoforge.segments.common.ports import TextPorts
from kinoforge.segments.common.text import clean_text

PROMPT_KEY = "animated_board"


@dataclass(frozen=True)
class Drawn:
    index: int
    board: dict | None
    error: str = ""
    answer: object = None


class BoardWriter:
    WORKERS = 6
    TEMPERATURE = 0.6
    NAME = "board"

    def __init__(self, ports: TextPorts, kit: Mapping) -> None:
        self.ports = ports
        self.catalog = KitCatalog(kit)
        self.schema = kit.get("schema") or {}
        self.ref = str((kit.get("stage") or {}).get("ref") or "")
        self.stages = StageWriter(ports, kit)
        self.repair = Repair(ports, self.NAME)

    def draw(
        self,
        rec: dict,
        targets: list[int] | None = None,
        route: ModelRef | None = None,
        max_tokens: int = 0,
        fixes: Mapping[int, list[str]] | None = None,
        tries: int = BoardCheck.TRIES,
    ) -> dict:
        story = rec.get("story") or {}
        scenes = story.get("scenes") or []
        wanted = [
            i
            for i in (targets if targets is not None else range(len(scenes)))
            if 0 <= i < len(scenes) and clean_text(scenes[i].get("narration"))
        ]
        if not wanted:
            return {"ok": False, "error": "no narrated scenes to draw"}
        if not self.catalog.format:
            return {"ok": False, "error": "the explainer kit is missing"}
        try:
            stage = self.stages.stage(rec, route, max_tokens, tries)
        except KitRefused as error:
            return {"ok": False, "error": str(error), **BoardCheck.refused(error.answer)}
        check = BoardCheck(self.schema, self.NAME, stage=stage, ref=self.ref)
        fixes = fixes or {}
        system = self.system(rec, stage)
        shared = self.catalog.shared(stage)
        with ThreadPoolExecutor(max_workers=min(self.WORKERS, len(wanted))) as pool:
            jobs = [
                pool.submit(
                    with_context(self._scene),
                    system,
                    story,
                    shared,
                    i,
                    route,
                    max_tokens,
                    check,
                    fixes.get(i) or [],
                    tries,
                )
                for i in wanted
            ]
            drawn = [job.result() for job in jobs]
        boards = [{"index": d.index, "board": d.board} for d in drawn if d.board is not None]
        errors = [
            {"index": d.index, "error": d.error, **BoardCheck.refused(d.answer)}
            for d in drawn
            if d.board is None
        ]
        if not boards:
            first = errors[0]["error"]
            return {"ok": False, "error": f"no board could be drawn: {first}", "errors": errors}
        return {"ok": True, "boards": boards, "errors": errors, "stage": stage}

    def system(self, rec: dict, stage: dict | None) -> str:
        elements = ((rec.get("story") or {}).get("elements") or {}).keys()
        params = {**self.catalog.pieces, **self.catalog.lists(stage, elements)}
        surfaces = "\n".join(
            self.ports.prompt(key, **params) for key in self.catalog.surfaces(stage)
        )
        return self.ports.prompt(
            PROMPT_KEY,
            board_format=self.catalog.format,
            surfaces=surfaces,
            language_rule=FilmLanguage.rule(self.ports, rec, "board text"),
            **params,
        )

    def _scene(
        self,
        system: str,
        story: dict,
        shared: dict,
        index: int,
        route: ModelRef | None,
        max_tokens: int,
        check: BoardCheck,
        fix: list[str],
        tries: int,
    ) -> Drawn:
        brief = self._brief(story, index, shared)
        drawn = (story.get("scenes") or [])[index].get("board") if fix else None
        board: object = drawn
        problems: list[str] = list(fix)
        for attempt in range(max(1, tries)):
            fresh = attempt == 0 and not (fix and board)
            prompt = brief if fresh else self.repair.again(brief, board, problems)
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
                board, problems = None, Repair.unread(error)
                continue
            except Exception as error:
                if isinstance(drawn, dict):
                    return Drawn(index, drawn)
                return Drawn(index, None, f"the board writer failed: {error}")
            board = answer.get(self.NAME, answer) if isinstance(answer, dict) else answer
            problems = check.problems(board)
            if not problems:
                return Drawn(index, board if isinstance(board, dict) else None)
        if isinstance(drawn, dict):
            return Drawn(index, drawn)
        return Drawn(index, None, f"the board was refused: {problems[0]}", board)

    @staticmethod
    def _brief(story: dict, index: int, shared: dict) -> str:
        scenes = story.get("scenes") or []

        def narration(i: int) -> str:
            return clean_text(scenes[i].get("narration")) if 0 <= i < len(scenes) else ""

        return json.dumps(
            {
                "topic": clean_text(story.get("logline")) or clean_text(story.get("title")),
                "scene": index + 1,
                "of": len(scenes),
                "narration": narration(index),
                "before": narration(index - 1),
                "after": narration(index + 1),
                **({"stage": shared} if shared else {}),
            },
            ensure_ascii=False,
        )
