import json
import threading

from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.explainer.boards import BoardCheck, BoardWriter
from kinoforge.segments.story.ports import StoryPorts

SCHEMA = {
    "type": "object",
    "required": ["mood", "beats"],
    "properties": {
        "mood": {"enum": ["happy", "sad"]},
        "beats": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["cue", "piece"],
                "properties": {
                    "cue": {"type": "string", "maxLength": 40},
                    "piece": {
                        "type": "object",
                        "required": ["type", "text"],
                        "properties": {"type": {"const": "title"}, "text": {"type": "string"}},
                    },
                },
            },
        },
    },
}
KIT = {"catalog": "PIECES: title", "schema": SCHEMA}
STAGE_SCHEMA = {
    "type": "object",
    "required": ["nodes"],
    "properties": {
        "nodes": {
            "type": "array",
            "items": {"type": "object", "required": ["id", "label"]},
        }
    },
}
STAGED = {**KIT, "stage": {"catalog": "STAGE: nodes", "schema": STAGE_SCHEMA}}
STAGE = {"nodes": [{"id": "bee", "label": "Bee"}]}
GOOD = {"mood": "happy", "beats": [{"cue": "bees", "piece": {"type": "title", "text": "Bees"}}]}
BAD = {"mood": "angry", "beats": []}
RECORD = {
    "input": {"language": ""},
    "story": {
        "logline": "Why bees matter",
        "scenes": [{"narration": "Bees pollinate."}, {"narration": ""}, {"narration": "Crops."}],
    },
}


class _Writer:
    def __init__(self, replies, missing=()):
        self.replies = dict(replies)
        self.missing = set(missing)
        self.prompts: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def prompt(self, key, **params):
        if key in self.missing:
            raise DefinitionError(f"required agent definition is unavailable: {key}")
        return f"<{key}>{params['catalog']}"

    def complete_json(self, task, system, user, *, route, temperature, max_tokens):
        scene = json.loads(user.split("\n\n")[0]).get("scene", "stage")
        with self.lock:
            self.prompts.append((system, user))
            queue = self.replies[scene]
            reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def ports(self) -> StoryPorts:
        return StoryPorts(
            complete=None, complete_json=self.complete_json, parse_json=json.loads,
            prompt=self.prompt,
            contract=lambda _n: "", language_rule=lambda *_: "", story_budget=lambda _o=None: 0,
        )


def test_every_narrated_scene_gets_a_checked_board():
    fake = _Writer({1: [GOOD], 3: [{"board": GOOD}]})
    result = BoardWriter(fake.ports(), KIT).draw(RECORD)
    assert result["ok"] is True
    assert [b["index"] for b in result["boards"]] == [0, 2]
    assert result["errors"] == []
    assert all(system == "<explainer_board>PIECES: title" for system, _ in fake.prompts)


def test_a_refused_board_goes_back_once_with_what_was_wrong():
    fake = _Writer({1: [BAD, GOOD], 3: [BAD, BAD]})
    result = BoardWriter(fake.ports(), KIT).draw(RECORD)
    assert [b["index"] for b in result["boards"]] == [0]
    assert result["errors"][0]["index"] == 2
    assert "refused" in result["errors"][0]["error"]
    repairs = [user for _, user in fake.prompts if "was refused" in user]
    assert len(repairs) == 2 and "board.mood" in repairs[0]


def test_an_answer_that_is_not_json_goes_back_once_too():
    broken = json.JSONDecodeError("Expecting ',' delimiter", "{", 1)
    fake = _Writer({1: [broken, GOOD], 3: [broken, broken]})
    result = BoardWriter(fake.ports(), KIT).draw(RECORD)
    assert [b["index"] for b in result["boards"]] == [0]
    assert "not valid JSON" in result["errors"][0]["error"]
    assert sum("was refused" in user for _, user in fake.prompts) == 2


def test_no_board_at_all_fails_the_operation():
    fake = _Writer({1: [RuntimeError("down")], 3: [RuntimeError("down")]})
    result = BoardWriter(fake.ports(), KIT).draw(RECORD)
    assert result["ok"] is False and "down" in result["error"]


def test_targets_pick_the_scenes_to_draw():
    fake = _Writer({3: [GOOD]})
    result = BoardWriter(fake.ports(), KIT).draw(RECORD, targets=[2])
    assert [b["index"] for b in result["boards"]] == [2]


def test_a_missing_kit_is_refused():
    result = BoardWriter(_Writer({}).ports(), {}).draw(RECORD)
    assert result == {"ok": False, "error": "the explainer kit is missing"}


def test_problems_name_where_they_are():
    problems = BoardCheck(SCHEMA).problems({"mood": "happy", "beats": [{"cue": "x" * 41}]})
    assert any(p.startswith("board.beats[0]") for p in problems)


def test_a_piece_that_fits_no_kind_is_told_what_is_wrong_in_its_own_kind():
    kinds = {
        "oneOf": [
            {
                "type": "object",
                "required": ["type", "text"],
                "properties": {"type": {"const": "title"}, "text": {"type": "string"}},
            },
            {
                "type": "object",
                "required": ["type", "car"],
                "properties": {
                    "type": {"const": "drive"},
                    "car": {"type": "string"},
                    "label": {"type": "string", "maxLength": 18},
                },
            },
        ]
    }
    schema = {"type": "object", "properties": {"piece": kinds}}
    problems = BoardCheck(schema).problems(
        {"piece": {"type": "drive", "car": "you", "label": "x" * 19}}
    )
    assert problems == [f"board.piece.label: {'x' * 19!r} is too long"]


def test_a_staged_kit_writes_the_stage_once_and_hands_it_to_every_board():
    fake = _Writer({"stage": [STAGE], 1: [GOOD], 3: [GOOD]})
    result = BoardWriter(fake.ports(), STAGED).draw(RECORD)
    assert result["stage"] == STAGE
    briefs = [json.loads(user) for system, user in fake.prompts if system.startswith("<explainer_board>")]
    assert len(briefs) == 2 and all(brief["stage"] == STAGE for brief in briefs)


def test_boards_get_the_stage_parts_it_has():
    coded = {"nodes": [], "files": [{"id": "stock", "lines": ["class Stock {}"]}]}
    fake = _Writer({"stage": [coded], 1: [GOOD], 3: [GOOD]})
    BoardWriter(fake.ports(), STAGED).draw(RECORD)
    briefs = [json.loads(user) for system, user in fake.prompts if system.startswith("<explainer_board>")]
    assert all(brief["stage"] == {"files": coded["files"]} for brief in briefs)


def test_a_story_keeps_its_stage_while_it_still_meets_the_kit():
    record = {**RECORD, "story": {**RECORD["story"], "stage": STAGE}}
    fake = _Writer({1: [GOOD], 3: [GOOD]})
    result = BoardWriter(fake.ports(), STAGED).draw(record)
    assert result["stage"] == STAGE
    assert not any(system.startswith("<explainer_stage>") for system, _ in fake.prompts)


def test_boards_are_drawn_without_a_stage_when_the_caller_has_no_stage_prompt():
    fake = _Writer({1: [GOOD], 3: [GOOD]}, missing={"explainer_stage"})
    result = BoardWriter(fake.ports(), STAGED).draw(RECORD)
    assert result["ok"] is True and result["stage"] is None
    assert all("stage" not in json.loads(user) for _, user in fake.prompts)


PARTED = {
    "board": "PIECES: title",
    "surfaces": [
        {"key": "diagram", "part": "nodes", "text": "DIAGRAM: show"},
        {"key": "road", "part": "road", "text": "ROAD: drive"},
        {"key": "map", "part": "places", "text": "MAP: pin"},
    ],
    "lists": [{"name": "ICONS", "pick": "icons", "keys": ["car", "bee", "map"]}],
}


def test_boards_read_only_the_surfaces_and_icons_their_stage_draws():
    stage = {"nodes": [], "road": {"side": "left"}, "surfaces": ["map"], "icons": ["car", "nope"]}
    fake = _Writer({"stage": [stage], 1: [GOOD], 3: [GOOD]})
    BoardWriter(fake.ports(), {**STAGED, "catalog": PARTED}).draw(RECORD)
    boards = [(system, json.loads(user)) for system, user in fake.prompts if system.startswith("<explainer_board>")]
    assert all(
        system == "<explainer_board>PIECES: title\nROAD: drive\nMAP: pin\nICONS: car" for system, _ in boards
    )
    assert all(brief["stage"] == {"road": {"side": "left"}} for _, brief in boards)


def test_a_stage_that_names_no_surfaces_keeps_the_whole_catalog():
    fake = _Writer({"stage": [STAGE], 1: [GOOD], 3: [GOOD]})
    BoardWriter(fake.ports(), {**STAGED, "catalog": PARTED}).draw(RECORD)
    systems = {system for system, _ in fake.prompts if system.startswith("<explainer_board>")}
    assert systems == {"<explainer_board>PIECES: title\nDIAGRAM: show\nROAD: drive\nMAP: pin\nICONS: car, bee, map"}
