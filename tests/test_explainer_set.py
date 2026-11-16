import json

from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.explainer.set import SetWriter
from kinoforge.segments.story.ports import StoryPorts

SET_SCHEMA = {
    "type": "object",
    "required": ["cast"],
    "properties": {
        "cast": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
            },
        }
    },
}
KIT = {"set": {"catalog": "SET: cast", "schema": SET_SCHEMA}}
MIA = {"id": "mia", "name": "Mia"}
LEO = {"id": "leo", "name": "Leo"}
RECORD = {
    "input": {"language": "", "description": "Two friends argue about tea."},
    "story": {
        "logline": "Tea or coffee",
        "characters": [
            {"name": "Mia", "description": "loves tea"},
            {"name": "Leo", "description": "coffee"},
        ],
        "scenes": [
            {"narration": "Tea is better.", "speaker": "Mia"},
            {"narration": "Coffee wins.", "speaker": "Leo"},
        ],
    },
}


class _Writer:
    def __init__(self, replies, missing=()):
        self.replies = list(replies)
        self.missing = set(missing)
        self.prompts: list[tuple[str, str]] = []

    def prompt(self, key, **params):
        if key in self.missing:
            raise DefinitionError(f"required agent definition is unavailable: {key}")
        return f"<{key}>{params['catalog']}"

    def complete_json(self, task, system, user, *, route, temperature, max_tokens):
        self.prompts.append((system, user))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def ports(self) -> StoryPorts:
        return StoryPorts(
            complete=None,
            complete_json=self.complete_json,
            parse_json=json.loads,
            prompt=self.prompt,
            contract=lambda _n: "",
            language_rule=lambda *_: "",
            story_budget=lambda _o=None: 0,
        )


def test_a_cast_set_names_everyone_who_speaks():
    fake = _Writer([{"set": {"cast": [MIA, LEO]}}])
    result = SetWriter(fake.ports(), KIT).write(RECORD, "cast", None, 0)
    assert result == {"ok": True, "set": {"cast": [MIA, LEO]}}
    sent = json.loads(fake.prompts[0][1])
    assert sent["presenter"] == "cast"
    assert [c["name"] for c in sent["characters"]] == ["Mia", "Leo"]
    assert sent["script"][1] == {"speaker": "Leo", "text": "Coffee wins."}
    assert fake.prompts[0][0] == "<explainer_set>SET: cast"


def test_a_speaker_left_out_goes_back_with_their_name():
    fake = _Writer([{"cast": [MIA]}, {"cast": [MIA, LEO]}])
    result = SetWriter(fake.ports(), KIT).write(RECORD, "cast", None, 0)
    assert result["ok"] is True
    assert "'Leo' speaks in the script" in fake.prompts[1][1]


def test_a_stick_presenter_is_a_cast_of_one():
    fake = _Writer([{"cast": [MIA, LEO]}, {"cast": [MIA]}])
    result = SetWriter(fake.ports(), KIT).write(RECORD, "stick", None, 0)
    assert result == {"ok": True, "set": {"cast": [MIA]}}
    assert "the presenter alone is a cast of one" in fake.prompts[1][1]
    assert json.loads(fake.prompts[0][1])["characters"] == []


def test_cast_ids_must_differ():
    fake = _Writer([{"cast": [MIA, {"id": "mia", "name": "Leo"}]}])
    result = SetWriter(fake.ports(), KIT).write(RECORD, "cast", None, 0, tries=1)
    assert result["ok"] is False
    assert "an id of their own" in result["error"]
    assert result["answer"] == {"cast": [MIA, {"id": "mia", "name": "Leo"}]}


def test_a_set_that_still_fits_is_kept():
    record = {**RECORD, "story": {**RECORD["story"], "set": {"cast": [MIA, LEO]}}}
    fake = _Writer([])
    assert SetWriter(fake.ports(), KIT).write(record, "cast", None, 0) == {
        "ok": True,
        "set": {"cast": [MIA, LEO]},
    }
    assert fake.prompts == []


def test_a_kept_set_missing_a_speaker_is_written_again():
    record = {**RECORD, "story": {**RECORD["story"], "set": {"cast": [MIA]}}}
    fake = _Writer([{"cast": [MIA, LEO]}])
    assert SetWriter(fake.ports(), KIT).write(record, "cast", None, 0)["set"] == {
        "cast": [MIA, LEO]
    }


def test_an_answer_that_is_not_json_is_tried_again():
    fake = _Writer([json.JSONDecodeError("bad", "x", 0), {"cast": [MIA, LEO]}])
    assert SetWriter(fake.ports(), KIT).write(RECORD, "cast", None, 0)["ok"] is True
    assert "not valid JSON" in fake.prompts[1][1]


def test_without_the_kit_or_the_prompt_there_is_no_set():
    assert SetWriter(_Writer([]).ports(), {}).write(RECORD, "cast", None, 0)["ok"] is False
    fake = _Writer([], missing={"explainer_set"})
    result = SetWriter(fake.ports(), KIT).write(RECORD, "cast", None, 0)
    assert result == {"ok": False, "error": "the set prompt is missing"}
