import json
import threading

from kinoforge.contract import AITask
from kinoforge.definitions.models import DefinitionError
from kinoforge.segments.animated.elements import ElementDrawer
from kinoforge.segments.common.ports import TextPorts

SHAPE_SCHEMA = {
    "type": "object",
    "required": ["box", "parts"],
    "properties": {
        "box": {
            "type": "object",
            "required": ["w", "h"],
            "properties": {"w": {"type": "number"}, "h": {"type": "number"}},
        },
        "parts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["d"],
                "properties": {"d": {"type": "string", "pattern": "^[MLZ0-9 ]+$"}},
            },
        },
    },
}
FORM = {"schema": SHAPE_SCHEMA, "limits": {"total": 40}}
TIRE = {"box": {"w": 100, "h": 100}, "parts": [{"d": "M10 10 L90 90 Z"}]}
BAD = {"box": {"w": 100, "h": 100}, "parts": [{"d": "<script>"}]}
LONG = {"box": {"w": 100, "h": 100}, "parts": [{"d": "M" + " 1" * 30}]}


class _Drawer:
    def __init__(self, replies, missing=False):
        self.replies = {word: list(queue) for word, queue in replies.items()}
        self.missing = missing
        self.calls: list[tuple[str, str, str, int]] = []
        self.lock = threading.Lock()

    def prompt(self, key, **params):
        if self.missing:
            raise DefinitionError(f"required agent definition is unavailable: {key}")
        if key.startswith("animated_repair"):
            parts = [str(params.get("brief", "")), "was refused", str(params["problems"])]
            return "\n\n".join([*parts, str(params.get("answer", ""))])
        return f"<{key}>{params['format']}"

    def complete_json(self, task, system, user, *, route, temperature, max_tokens):
        word = json.loads(user.split("\n\n")[0])["picture"]
        with self.lock:
            self.calls.append((task, word, user, max_tokens))
            reply = self.replies[word].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def ports(self) -> TextPorts:
        return TextPorts(
            complete=None,
            complete_json=self.complete_json,
            parse_json=json.loads,
            prompt=self.prompt,
            contract=lambda _n: "",
            language_rule=lambda *_: "",
            story_budget=lambda _o=None: 0,
        )


def test_each_picture_is_drawn_alone_on_the_element_task():
    fake = _Drawer({"car tire": [TIRE], "gap": [{"shape": TIRE}]})
    wants = [{"word": "car tire", "for": "Vehicle"}, {"word": "gap"}]
    result = ElementDrawer(fake.ports(), FORM, "animated_element").draw(
        wants, "bridges", None, 3000
    )
    assert result == {
        "ok": True,
        "elements": [{"word": "car tire", "shape": TIRE}, {"word": "gap", "shape": TIRE}],
        "errors": [],
    }
    assert {task for task, *_ in fake.calls} == {AITask.STORY_ELEMENT}
    assert all(tokens == 3000 for *_, tokens in fake.calls)
    brief = json.loads(next(user for _, word, user, _ in fake.calls if word == "car tire"))
    assert brief == {"picture": "car tire", "stands_for": "Vehicle", "topic": "bridges"}


def test_a_refused_drawing_goes_back_once_with_what_was_wrong():
    fake = _Drawer({"gap": [BAD, TIRE], "leaf": [BAD, BAD]})
    result = ElementDrawer(fake.ports(), FORM, "animated_element").draw(
        [{"word": "gap"}, {"word": "leaf"}], "", None, 0
    )
    assert result["elements"] == [{"word": "gap", "shape": TIRE}]
    assert result["errors"][0]["word"] == "leaf"
    assert "refused" in result["errors"][0]["error"]
    repairs = [user for _, _, user, _ in fake.calls if "was refused" in user]
    assert len(repairs) == 2 and "drawing.parts[0].d" in repairs[0]


def test_a_drawing_is_tried_as_often_as_the_caller_says_and_a_refused_one_comes_back():
    fake = _Drawer({"leaf": [BAD, BAD, BAD]})
    result = ElementDrawer(fake.ports(), FORM, "animated_element").draw(
        [{"word": "leaf"}], "", None, 0, tries=3
    )
    assert sum("was refused" in user for _, _, user, _ in fake.calls) == 2
    assert result["ok"] is False and result["errors"][0]["answer"] == BAD


def test_paths_past_the_kit_limit_are_refused():
    fake = _Drawer({"gap": [LONG, LONG]})
    result = ElementDrawer(fake.ports(), FORM, "animated_element").draw(
        [{"word": "gap"}], "", None, 0
    )
    assert result["ok"] is False
    assert "at most 40" in result["error"]


def test_a_failing_model_names_the_picture_it_could_not_draw():
    fake = _Drawer({"gap": [RuntimeError("model down")], "leaf": [TIRE]})
    result = ElementDrawer(fake.ports(), FORM, "animated_element").draw(
        [{"word": "gap"}, {"word": "leaf"}], "", None, 0
    )
    assert result["errors"] == [{"word": "gap", "error": "the drawing model failed: model down"}]


def test_wants_are_cleaned_deduplicated_and_capped():
    words = [{"word": f"thing {i}"} for i in range(ElementDrawer.MOST + 3)]
    fake = _Drawer({"Thing 0": [TIRE], **{w["word"]: [TIRE] for w in words}})
    wants = [{"word": "Thing 0"}, *words, {"word": "  "}, "junk"]
    result = ElementDrawer(fake.ports(), FORM, "animated_element").draw(wants, "", None, 0)
    drawn = [item["word"] for item in result["elements"]]
    assert drawn == ["Thing 0"] + [f"thing {i}" for i in range(1, ElementDrawer.MOST)]


def test_nothing_is_asked_without_wants_a_format_or_a_prompt():
    fake = _Drawer({})
    assert (
        ElementDrawer(fake.ports(), FORM, "animated_element").draw([], "", None, 0)["error"]
        == "no pictures to draw"
    )
    no_form = ElementDrawer(fake.ports(), {}, "animated_element").draw(
        [{"word": "gap"}], "", None, 0
    )
    assert "element format" in no_form["error"]
    missing = ElementDrawer(_Drawer({}, missing=True).ports(), FORM, "animated_element")
    assert missing.draw([{"word": "gap"}], "", None, 0)["error"] == "the drawing prompt is missing"
    assert fake.calls == []
