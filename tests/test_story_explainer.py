import json
import threading

from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.explainer.boards import BoardCheck, BoardWriter
from kinoforge.segments.story.explainer.stage import StageWriter
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

    problems = BoardCheck(schema).problems({"piece": {"type": "diagram", "car": "you"}})
    assert problems == ["board.piece: type 'diagram' is not a piece kind; use one of: drive, title"]


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


REFS = {
    "type": "object",
    "required": ["mood", "beats"],
    "properties": {
        "mood": {"enum": ["happy"]},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "piece": {
                        "type": "object",
                        "properties": {"type": {"const": "show"}, "node": {"type": "string", "x-stage": "nodes"}},
                    }
                },
            },
        },
    },
}
SHOWN = {"mood": "happy", "beats": [{"cue": "bees", "piece": {"type": "show", "node": "bee"}}]}
STRAY = {"mood": "happy", "beats": [{"cue": "bees", "piece": {"type": "show", "node": "hive-cell"}}]}
REFERRED = {**STAGED, "schema": REFS, "stage": {**STAGED["stage"], "ref": "x-stage"}}


def test_a_board_naming_a_part_off_the_stage_goes_back_with_the_stage_ids():
    fake = _Writer({"stage": [STAGE], 1: [STRAY, SHOWN], 3: [SHOWN]})
    result = BoardWriter(fake.ports(), REFERRED).draw(RECORD)
    assert result["ok"] is True and [b["index"] for b in result["boards"]] == [0, 2]
    repair = next(user for _, user in fake.prompts if "was refused" in user)
    assert "'hive-cell' is not on the STAGE; use one of: bee" in repair


def test_a_stage_without_the_part_says_to_leave_the_piece_out():
    problems = BoardCheck(REFS, stage={"nodes": []}, ref="x-stage").problems(SHOWN)
    assert problems == ["board.beats[0].piece.node: 'bee' is not on the STAGE, which has no nodes: leave this piece out"]


def test_a_refused_stage_fails_the_boards_instead_of_drawing_without_it():
    fake = _Writer({"stage": [{"nodes": "x"}, {"nodes": "x"}]})
    result = BoardWriter(fake.ports(), STAGED).draw(RECORD)
    assert result["ok"] is False and result["error"].startswith("the stage was refused")
    assert not any(system.startswith("<explainer_board>") for system, _ in fake.prompts)


def test_fixes_send_the_drawn_board_back_with_what_did_not_fit():
    scenes = [{"narration": "Bees pollinate.", "board": GOOD}, {"narration": ""}, {"narration": "Crops."}]
    record = {**RECORD, "story": {**RECORD["story"], "scenes": scenes}}
    fake = _Writer({1: [GOOD]})
    tight = "board.beats[0].piece.text: too long to read on a vertical frame; keep it under 20 characters"
    result = BoardWriter(fake.ports(), KIT).draw(record, targets=[0], fixes={0: [tight]})
    assert result["ok"] is True
    (_, user), = fake.prompts
    assert "was refused" in user and tight in user and json.dumps(GOOD) in user


def test_a_fix_the_writer_cannot_make_keeps_the_board_it_drew():
    scenes = [{"narration": "Bees pollinate.", "board": GOOD}, {"narration": ""}, {"narration": "Crops."}]
    record = {**RECORD, "story": {**RECORD["story"], "scenes": scenes}}
    fake = _Writer({1: [BAD, BAD]})
    result = BoardWriter(fake.ports(), KIT).draw(record, targets=[0], fixes={0: ["too long"]})
    assert result["boards"] == [{"index": 0, "board": GOOD}] and result["errors"] == []


def test_write_stage_returns_the_stage_alone():
    fake = _Writer({"stage": [STAGE]})
    assert StageWriter(fake.ports(), STAGED).write(RECORD, None, 0) == {"ok": True, "stage": STAGE}
    assert not any(system.startswith("<explainer_board>") for system, _ in fake.prompts)


def test_the_stage_reads_the_makers_brief_beside_the_narration():
    fake = _Writer({"stage": [STAGE]})
    record = {**RECORD, "input": {"language": "", "description": "Show the AWS logo."}}
    StageWriter(fake.ports(), STAGED).write(record, None, 0)
    sent = json.loads(fake.prompts[0][1])
    assert sent["brief"] == "Show the AWS logo."
    assert sent["narration"] == ["Bees pollinate.", "", "Crops."]


def test_write_stage_fails_without_a_stage_prompt():
    fake = _Writer({}, missing={"explainer_stage"})
    result = StageWriter(fake.ports(), STAGED).write(RECORD, None, 0)
    assert result["ok"] is False and "stage prompt" in result["error"]


def test_boards_list_the_store_items_the_caller_resolved_for_the_stage():
    stage = {"nodes": [], "surfaces": [], "icons": ["car", "postgresql", "nope"]}
    record = {**RECORD, "story": {**RECORD["story"], "stage": stage, "elements": {"postgresql": {}}}}
    fake = _Writer({1: [GOOD], 3: [GOOD]})
    BoardWriter(fake.ports(), {**STAGED, "catalog": PARTED}).draw(record)
    systems = {system for system, _ in fake.prompts if system.startswith("<explainer_board>")}
    assert systems == {"<explainer_board>PIECES: title\nICONS: car, postgresql"}
