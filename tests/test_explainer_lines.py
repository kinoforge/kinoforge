import json

from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.story.explainer.lines import LineDirector
from kinoforge.segments.story.ports import StoryPorts

REF = "x-ref"
LINE = {
    "type": "object",
    "required": ["line"],
    "properties": {
        "line": {"type": "integer", "minimum": 1},
        "to": {"type": "string", REF: "cast"},
        "acts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["who"],
                "properties": {
                    "who": {"type": "string", REF: "cast"},
                    "pose": {"enum": ["talk", "shrug"]},
                },
            },
        },
        "draw": {"enum": ["beside", "full"]},
    },
}
KIT = {
    "ref": REF,
    "draws": ["beside", "full"],
    "direction": {
        "catalog": "LINES",
        "schema": {
            "type": "object",
            "required": ["lines"],
            "properties": {"lines": {"type": "array", "items": LINE}},
        },
    },
}
SET = {"cast": [{"id": "mia", "name": "Mia"}, {"id": "leo", "name": "Leo"}]}
RECORD = {
    "input": {"language": ""},
    "story": {
        "logline": "Tea or coffee",
        "scenes": [
            {"narration": "Tea is better.", "speaker": "Mia"},
            {"narration": "Coffee wins.", "speaker": "Leo"},
            {"narration": "Look at the caffeine.", "speaker": "Mia"},
            {"narration": "Fine, both.", "speaker": "leo"},
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
        return self.replies.pop(0)

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


def _direct(replies, presenter="cast", draws=1, tries=2, record=RECORD):
    fake = _Writer(replies)
    return fake, LineDirector(fake.ports(), KIT).direct(
        record, SET, presenter, None, 0, draws, tries
    )


def test_every_scene_gets_a_line_spoken_by_its_cast_member():
    answer = {
        "lines": [{"line": 1, "to": "leo", "acts": [{"who": "mia", "pose": "talk"}]}, {"line": 2}]
    }
    fake, result = _direct([answer])
    assert result["ok"] is True and result["errors"] == []
    assert [line["speaker"] for line in result["lines"]] == ["mia", "leo", "mia", "leo"]
    assert result["lines"][0] == {
        "to": "leo",
        "acts": [{"who": "mia", "pose": "talk"}],
        "speaker": "mia",
    }
    assert result["lines"][3] == {"speaker": "leo"}
    sent = json.loads(fake.prompts[0][1])
    assert sent["script"][0] == {"line": 1, "speaker": "mia", "text": "Tea is better."}
    assert sent["draws"] == "at most 1 lines draw, never the first"
    assert fake.prompts[0][0] == "<explainer_lines>LINES"


def test_a_cast_draws_no_more_than_allowed_and_never_on_the_first_line():
    answer = {"lines": [{"line": n, "draw": "full"} for n in (1, 2, 3, 4)]}
    _, result = _direct([answer], draws=2)
    assert [line.get("draw") for line in result["lines"]] == [None, "full", "full", None]


def test_a_stick_presenter_draws_on_every_line():
    answer = {"lines": [{"line": 1, "draw": "full"}, {"line": 2}]}
    _, result = _direct([answer], presenter="stick", draws=0)
    assert [line["draw"] for line in result["lines"]] == ["full", "beside", "beside", "beside"]
    assert {line["speaker"] for line in result["lines"]} == {"mia", "leo"}


def test_a_name_off_the_set_goes_back_with_the_cast_ids():
    bad = {"lines": [{"line": 1, "to": "zed"}]}
    fake, result = _direct([bad, {"lines": [{"line": 1, "to": "leo"}]}])
    assert result["lines"][0]["to"] == "leo"
    assert "use one of: mia, leo" in fake.prompts[1][1]


def test_a_line_still_wrong_after_its_tries_is_left_plain_and_named():
    bad = {
        "lines": [{"line": 1, "to": "zed"}, {"line": 2, "acts": [{"who": "leo", "pose": "shrug"}]}]
    }
    _, result = _direct([bad], tries=1)
    assert result["ok"] is True
    assert result["lines"][0] == {"speaker": "mia"}
    assert result["lines"][1]["acts"] == [{"who": "leo", "pose": "shrug"}]
    assert any(error.startswith("line 1:") for error in result["errors"])


def test_talking_to_oneself_is_talking_to_the_viewer():
    _, result = _direct([{"lines": [{"line": 1, "to": "mia"}]}])
    assert "to" not in result["lines"][0]


def test_no_lines_at_all_fails_with_the_answer():
    _, result = _direct([{"nope": 1}], tries=1)
    assert result["ok"] is False and result["answer"] == {"nope": 1}


def test_without_a_cast_or_the_prompt_nothing_is_directed():
    fake = _Writer([])
    assert (
        LineDirector(fake.ports(), KIT).direct(RECORD, {"cast": []}, "cast", None, 0, 1)["ok"]
        is False
    )
    fake = _Writer([], missing={"explainer_lines"})
    result = LineDirector(fake.ports(), KIT).direct(RECORD, SET, "cast", None, 0, 1)
    assert result == {"ok": False, "error": "the lines prompt is missing"}
