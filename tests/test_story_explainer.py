import json
import threading

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
    def __init__(self, replies):
        self.replies = dict(replies)
        self.prompts: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def complete_json(self, task, system, user, *, route, temperature, max_tokens):
        scene = json.loads(user.split("\n\n")[0])["scene"]
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
            prompt=lambda key, **params: f"<{key}>{params['catalog']}",
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
