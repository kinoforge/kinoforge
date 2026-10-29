"""Explainer boards: what each scene shows instead of a picture, as data the caller's renderer
draws. One board per scene, written side by side from its narration against the caller's kit
(the catalog a writer reads and the JSON schema a board must meet), checked, and sent back to
the writer once with what was wrong. The video's stage (stage.py) is written first, so every
board names the same diagram nodes and code files."""

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from kinoforge.contract import AITask, ModelRef
from kinoforge.observ import with_context
from kinoforge.segments.story.agent import clean_text
from kinoforge.segments.story.explainer.check import BoardCheck
from kinoforge.segments.story.explainer.stage import StageWriter
from kinoforge.segments.story.languages import language_name
from kinoforge.segments.story.ports import StoryPorts

PROMPT_KEY = "explainer_board"


@dataclass(frozen=True)
class Drawn:
    index: int
    board: dict | None
    error: str = ""


class BoardWriter:
    WORKERS = 6
    TEMPERATURE = 0.6

    def __init__(self, ports: StoryPorts, kit: Mapping) -> None:
        self.ports = ports
        self.catalog = str(kit.get("catalog") or "")
        self.check = BoardCheck(kit.get("schema") or {})
        self.stages = StageWriter(ports, kit)

    def draw(
        self,
        rec: dict,
        targets: list[int] | None = None,
        route: ModelRef | None = None,
        max_tokens: int = 0,
    ) -> dict:
        story = rec.get("story") or {}
        scenes = story.get("scenes") or []
        wanted = [i for i in (targets if targets is not None else range(len(scenes)))
                  if 0 <= i < len(scenes) and clean_text(scenes[i].get("narration"))]
        if not wanted:
            return {"ok": False, "error": "no narrated scenes to draw"}
        if not self.catalog:
            return {"ok": False, "error": "the explainer kit is missing"}
        stage = self.stages.stage(rec, route, max_tokens)
        language = str((rec.get("input") or {}).get("language") or "")
        system = self.ports.prompt(
            PROMPT_KEY,
            catalog=self.catalog,
            language_rule=self.ports.language_rule("board text", language_name(language)),
        )
        with ThreadPoolExecutor(max_workers=min(self.WORKERS, len(wanted))) as pool:
            jobs = [
                pool.submit(with_context(self._scene), system, story, stage, i, route, max_tokens)
                for i in wanted
            ]
            drawn = [job.result() for job in jobs]
        boards = [{"index": d.index, "board": d.board} for d in drawn if d.board is not None]
        errors = [{"index": d.index, "error": d.error} for d in drawn if d.board is None]
        if not boards:
            return {"ok": False, "error": f"no board could be drawn: {errors[0]['error']}"}
        return {"ok": True, "boards": boards, "errors": errors, "stage": stage}

    def _scene(
        self,
        system: str,
        story: dict,
        stage: dict | None,
        index: int,
        route: ModelRef | None,
        max_tokens: int,
    ) -> Drawn:
        brief = self._brief(story, index, stage)
        board: object = None
        problems: list[str] = []
        for attempt in range(2):
            prompt = brief if attempt == 0 else self.check.repair(brief, board, problems)
            try:
                answer = self.ports.complete_json(
                    AITask.STORY_BOARD, system, prompt, route=route or ModelRef(),
                    temperature=self.TEMPERATURE, max_tokens=max_tokens,
                )
            except Exception as error:
                return Drawn(index, None, f"the board writer failed: {error}")
            board = answer.get("board", answer) if isinstance(answer, dict) else answer
            problems = self.check.problems(board)
            if not problems:
                return Drawn(index, board if isinstance(board, dict) else None)
        return Drawn(index, None, f"the board was refused: {problems[0]}")

    @staticmethod
    def _shared(stage: dict | None) -> dict:
        """The parts of the stage a board may point at: the ones it has."""
        return {name: part for name, part in (stage or {}).items() if part}

    @staticmethod
    def _brief(story: dict, index: int, stage: dict | None = None) -> str:
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
                **({"stage": shared} if (shared := BoardWriter._shared(stage)) else {}),
            },
            ensure_ascii=False,
        )
