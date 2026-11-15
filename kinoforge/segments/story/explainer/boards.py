"""Explainer boards: what each scene shows instead of a picture, as data the caller's renderer
draws. One board per scene, written side by side from its narration against the caller's kit
(the catalog a writer reads and the JSON schema a board must meet), checked, and sent back to
the writer once with what was wrong. The video's stage (stage.py) is written first, so every
board names the same diagram nodes, code files and road side, and reads only the parts of the
catalog the stage says this video draws."""

import json
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from kinoforge.contract import AITask, ModelRef
from kinoforge.observ import with_context
from kinoforge.segments.story.agent import clean_text
from kinoforge.segments.story.explainer.check import BoardCheck
from kinoforge.segments.story.explainer.stage import StageRefused, StageWriter
from kinoforge.segments.story.languages import language_name
from kinoforge.segments.story.ports import StoryPorts

PROMPT_KEY = "explainer_board"


@dataclass(frozen=True)
class Drawn:
    index: int
    board: dict | None
    error: str = ""


class KitCatalog:
    """The kit's catalog cut to one video. A catalog in parts keeps its board text, the surfaces
    the stage names or has the part of, and each list narrowed to the stage's picks; a stage
    that names no surfaces or picks keeps them all. A catalog given as one text is used whole."""

    SURFACES = "surfaces"

    @staticmethod
    def text(catalog: object, stage: dict | None, extra: Iterable[str] = ()) -> str:
        if not isinstance(catalog, Mapping):
            return str(catalog or "")
        stage = stage or {}
        named = stage.get(KitCatalog.SURFACES)
        surfaces = [
            str(part.get("text") or "")
            for part in catalog.get("surfaces") or []
            if isinstance(part, Mapping)
            and (not isinstance(named, list) or part.get("key") in named
                 or stage.get(str(part.get("part"))))
        ]
        lists = []
        extra = set(extra)
        for item in KitCatalog._lists(catalog):
            keys = [str(key) for key in item.get("keys") or []]
            picks = [str(key) for key in stage.get(str(item.get("pick"))) or []]
            picked = set(picks)
            known = set(keys)
            kept = [key for key in keys if key in picked] + [
                key for key in dict.fromkeys(picks) if key in extra and key not in known
            ]
            kept = kept or keys
            lists.append(f"{item.get('name')}: {', '.join(kept)}")
        return "\n".join([str(catalog.get("board") or ""), *surfaces, *lists])

    @staticmethod
    def shared(catalog: object, stage: dict | None) -> dict:
        """The stage parts a board points at: the ones it has, less the picks that cut the
        catalog."""
        picks = {KitCatalog.SURFACES, *(str(i.get("pick")) for i in KitCatalog._lists(catalog))}
        return {name: part for name, part in (stage or {}).items() if part and name not in picks}

    @staticmethod
    def _lists(catalog: object) -> list[Mapping]:
        if not isinstance(catalog, Mapping):
            return []
        return [item for item in catalog.get("lists") or [] if isinstance(item, Mapping)]


class BoardWriter:
    WORKERS = 6
    TEMPERATURE = 0.6

    def __init__(self, ports: StoryPorts, kit: Mapping) -> None:
        self.ports = ports
        self.catalog = kit.get("catalog") or ""
        self.schema = kit.get("schema") or {}
        self.ref = str((kit.get("stage") or {}).get("ref") or "")
        self.stages = StageWriter(ports, kit)

    def draw(
        self,
        rec: dict,
        targets: list[int] | None = None,
        route: ModelRef | None = None,
        max_tokens: int = 0,
        fixes: Mapping[int, list[str]] | None = None,
    ) -> dict:
        story = rec.get("story") or {}
        scenes = story.get("scenes") or []
        wanted = [i for i in (targets if targets is not None else range(len(scenes)))
                  if 0 <= i < len(scenes) and clean_text(scenes[i].get("narration"))]
        if not wanted:
            return {"ok": False, "error": "no narrated scenes to draw"}
        if not self.catalog:
            return {"ok": False, "error": "the explainer kit is missing"}
        try:
            stage = self.stages.stage(rec, route, max_tokens)
        except StageRefused as error:
            return {"ok": False, "error": str(error)}
        check = BoardCheck(self.schema, stage=stage, ref=self.ref)
        fixes = fixes or {}
        language = str((rec.get("input") or {}).get("language") or "")
        system = self.ports.prompt(
            PROMPT_KEY,
            catalog=KitCatalog.text(self.catalog, stage, (story.get("elements") or {}).keys()),
            language_rule=self.ports.language_rule(
                "board text", language_name(language, self.ports.languages)
            ),
        )
        shared = KitCatalog.shared(self.catalog, stage)
        with ThreadPoolExecutor(max_workers=min(self.WORKERS, len(wanted))) as pool:
            jobs = [
                pool.submit(
                    with_context(self._scene), system, story, shared, i, route, max_tokens,
                    check, fixes.get(i) or [],
                )
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
        shared: dict,
        index: int,
        route: ModelRef | None,
        max_tokens: int,
        check: BoardCheck,
        fix: list[str],
    ) -> Drawn:
        brief = self._brief(story, index, shared)
        drawn = (story.get("scenes") or [])[index].get("board") if fix else None
        board: object = drawn
        problems: list[str] = list(fix)
        for attempt in range(2):
            fresh = attempt == 0 and not (fix and board)
            prompt = brief if fresh else check.repair(brief, board, problems)
            try:
                answer = self.ports.complete_json(
                    AITask.STORY_BOARD, system, prompt, route=route or ModelRef(),
                    temperature=self.TEMPERATURE, max_tokens=max_tokens,
                )
            except json.JSONDecodeError as error:
                # An answer that is not JSON goes back like a refused one, for the writer to fix.
                board, problems = None, [f"the answer was not valid JSON ({error})"]
                continue
            except Exception as error:
                if isinstance(drawn, dict):
                    return Drawn(index, drawn)
                return Drawn(index, None, f"the board writer failed: {error}")
            board = answer.get("board", answer) if isinstance(answer, dict) else answer
            problems = check.problems(board)
            if not problems:
                return Drawn(index, board if isinstance(board, dict) else None)
        if isinstance(drawn, dict):
            return Drawn(index, drawn)
        return Drawn(index, None, f"the board was refused: {problems[0]}")

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
