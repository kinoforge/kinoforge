import json

from kinoforge.segments.animated.skit.lines import LineDirector
from kinoforge.segments.animated.skit.rules import LineRules, SetRules
from kinoforge.segments.animated.skit.set import SetWriter
from kinoforge.segments.common.ports import TextPorts

KIT = {
    "ref": "x-ref",
    "words": {"draws": ["beside", "full"], "places": ["left", "center", "right"]},
    "furniture": {"office": ["window", "clock"], "plain": []},
    "pictures": {"hat": [], "head": [], "holds": [], "kind": [], "icon": []},
    "set": {"format": "SET", "schema": {"type": "object", "required": ["cast"]}},
    "direction": {
        "format": "LINES",
        "changes": [],
        "schema": {"type": "object", "required": ["lines"]},
    },
}
EMPTY = ["none", "nothing", "n/a"]
MIA = {"id": "mia", "name": "Mia", "place": "left"}
LEO = {"id": "leo", "name": "Leo", "place": "right"}
STORY = {
    "scenes": [
        {"narration": "Tea is better.", "speaker": "Mia"},
        {"narration": "Coffee wins.", "speaker": "Leo"},
        {"narration": "Fine.", "speaker": "Mia"},
        {"narration": "Both.", "speaker": "Leo"},
    ]
}
RECORD = {"input": {"language": ""}, "story": STORY}


class _Writer:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def prompt(self, key, **params):
        if key.startswith("animated_repair"):
            return "\n\n".join(str(params.get(name, "")) for name in ("brief", "problems"))
        return f"<{key}>"

    def complete_json(self, task, system, user, *, route, temperature, max_tokens):
        self.prompts.append((system, user))
        return self.replies.pop(0)

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


def _set_problems(drawn, presenter="cast"):
    return SetRules(KIT, EMPTY).problems(drawn, STORY, presenter)


def test_a_hand_holding_nothing_is_refused_by_its_field():
    drawn = {"cast": [{**MIA, "holds": "None"}, {**LEO, "hat": "n/a", "holds": "mug"}]}
    assert _set_problems(drawn) == [
        "set.cast[0].holds: 'None' names nothing; leave holds out",
        "set.cast[1].hat: 'n/a' names nothing; leave hat out",
    ]


def test_a_prop_or_card_icon_naming_nothing_is_refused():
    drawn = {
        "cast": [MIA, LEO],
        "props": [{"kind": "nothing", "place": "center"}],
        "card": {"kind": "score", "title": "Cups", "icon": "none"},
    }
    assert _set_problems(drawn) == [
        "set.props[0].kind: 'nothing' names nothing; leave this prop out",
        "set.card.icon: 'none' names nothing; leave icon out",
    ]


def test_two_people_cannot_start_on_one_place_unless_one_walks_on_later():
    assert _set_problems({"cast": [MIA, {**LEO, "place": "left"}]}) == [
        "set.cast[1].place: Leo and Mia both start at left; give each their own place"
    ]
    assert _set_problems({"cast": [MIA, {**LEO, "place": "left", "enters": True}]}) == []


def test_a_prop_the_backdrop_already_draws_is_refused():
    drawn = {
        "backdrop": "office",
        "cast": [MIA, LEO],
        "props": [{"kind": "Window", "place": "center"}, {"kind": "plant", "place": "left"}],
    }
    assert _set_problems(drawn) == [
        "set.props[0].kind: the office backdrop already has a Window; leave this prop out"
    ]
    assert _set_problems({**drawn, "backdrop": "plain"}) == []


def test_a_set_with_a_semantic_problem_goes_back_in_the_same_loop():
    bad = {"cast": [{**MIA, "holds": "none"}, LEO]}
    good = {"cast": [MIA, LEO]}
    fake = _Writer([bad, good])
    result = SetWriter(fake.ports(), KIT, "animated_set", EMPTY).write(RECORD, "cast", None, 0)
    assert result == {"ok": True, "set": good}
    assert "set.cast[0].holds: 'none' names nothing" in fake.prompts[1][1]


def test_a_kept_set_with_a_semantic_problem_is_written_again():
    kept = {"cast": [MIA, {**LEO, "place": "left"}]}
    record = {**RECORD, "story": {**STORY, "set": kept}}
    fake = _Writer([{"cast": [MIA, LEO]}])
    assert SetWriter(fake.ports(), KIT, "animated_set", EMPTY).write(record, "cast", None, 0)[
        "set"
    ] == {"cast": [MIA, LEO]}


SET = {"cast": [MIA, LEO]}
SPEAKERS = ["mia", "leo", "mia", "leo"]


def _line_problems(items, drawn=SET, span=(1, 4)):
    rules = LineRules(drawn, KIT["words"]["places"])
    return rules.problems(items, SPEAKERS, rules.start, span)


def test_a_move_onto_a_place_someone_holds_is_refused():
    items = [{"line": 2, "acts": [{"who": "mia", "pose": "talk"}, {"who": "leo", "move": "left"}]}]
    assert _line_problems(items) == [
        "direction.lines[0].acts[1].move: leo moves to left where mia stands; "
        "pick a free place or move mia away first"
    ]


def test_two_people_may_swap_places_or_follow_someone_who_left():
    swap = [{"line": 1, "acts": [{"who": "mia", "move": "right"}, {"who": "leo", "move": "left"}]}]
    assert _line_problems(swap) == []
    follow = [
        {"line": 1, "acts": [{"who": "mia", "move": "off"}]},
        {"line": 2, "acts": [{"who": "leo", "move": "left"}]},
    ]
    assert _line_problems(follow) == []


def test_a_place_freed_and_taken_again_is_tracked_line_by_line():
    items = [
        {"line": 1, "acts": [{"who": "mia", "move": "center"}]},
        {"line": 2, "acts": [{"who": "leo", "move": "center"}]},
    ]
    assert _line_problems(items) == [
        "direction.lines[1].acts[0].move: leo moves to center where mia stands; "
        "pick a free place or move mia away first"
    ]


def test_a_card_change_without_a_card_is_refused():
    items = [{"line": 3, "card": [{"do": "tag", "text": "tea"}]}]
    assert _line_problems(items) == ["direction.lines[0].card: the set has no card; leave card out"]
    carded = {**SET, "card": {"kind": "score", "title": "Cups"}}
    assert _line_problems(items, drawn=carded) == []


def test_a_later_chunk_starts_from_where_the_lines_before_left_everyone():
    rules = LineRules(SET, KIT["words"]["places"])
    _, at = rules.played({"acts": [{"who": "mia", "move": "center"}]}, "mia", rules.start)
    items = [{"line": 3, "acts": [{"who": "leo", "move": "center"}]}]
    assert rules.problems(items, SPEAKERS, at, (3, 4)) == [
        "direction.lines[0].acts[0].move: leo moves to center where mia stands; "
        "pick a free place or move mia away first"
    ]


def test_a_speaker_walking_on_takes_a_free_place_when_their_own_is_taken():
    drawn = {"cast": [MIA, {**LEO, "place": "left", "enters": True}]}
    rules = LineRules(drawn, KIT["words"]["places"])
    line, at = rules.played({}, "leo", rules.start)
    assert line == {"acts": [{"who": "leo", "move": "center"}]}
    assert at == {"mia": "left", "leo": "center"}


def test_a_clash_goes_back_to_the_director_in_the_same_loop():
    bad = {"lines": [{"line": 1, "acts": [{"who": "leo", "move": "left"}]}]}
    good = {"lines": [{"line": 1, "acts": [{"who": "leo", "move": "center"}]}]}
    fake = _Writer([bad, good])
    result = LineDirector(fake.ports(), KIT, "animated_lines").direct(
        RECORD, SET, "cast", None, 0, 0
    )
    assert result["ok"] is True and result["errors"] == []
    assert result["lines"][0]["acts"] == [{"who": "leo", "move": "center"}]
    assert "leo moves to left where mia stands" in fake.prompts[1][1]


def test_a_clash_or_a_card_change_left_after_the_tries_never_reaches_the_film():
    bad = {
        "lines": [
            {
                "line": 1,
                "acts": [
                    {"who": "leo", "move": "left", "pose": "talk"},
                    {"who": "mia", "move": "left"},
                ],
                "card": [{"do": "tag", "text": "tea"}],
            },
            {"line": 2, "acts": [{"who": "leo", "move": "center"}]},
        ]
    }
    fake = _Writer([bad])
    result = LineDirector(fake.ports(), KIT, "animated_lines").direct(
        RECORD, SET, "cast", None, 0, 0, tries=1
    )
    assert result["ok"] is True
    assert result["lines"][0] == {"acts": [{"who": "leo", "pose": "talk"}], "speaker": "mia"}
    assert result["lines"][1]["acts"] == [{"who": "leo", "move": "center"}]
    assert any("was refused" in error for error in result["errors"])


def test_an_act_or_face_the_cast_cannot_play_goes_back_to_the_director():
    words = {"actions": ["idle", "talk", "wave"], "faces": ["neutral", "sad"]}
    rules = LineRules(SET, KIT["words"]["places"], words)
    items = [{"line": 1, "acts": [{"who": "mia", "act": "shrug", "face": "sad"}]}]
    assert rules.problems(items, SPEAKERS, rules.start, (1, 1)) == [
        "direction.lines[0].acts[0].act: 'shrug' is not one this cast can play; "
        "use one of idle, talk, wave or leave act out"
    ]
    line, _ = rules.played(
        {"acts": [{"who": "mia", "act": "shrug", "face": "happy"}, {"who": "leo", "act": "wave"}]},
        "mia",
        rules.start,
    )
    assert line == {"acts": [{"who": "leo", "act": "wave"}]}


def test_a_kit_without_listed_acts_lets_every_act_through():
    rules = LineRules(SET, KIT["words"]["places"])
    items = [{"line": 1, "acts": [{"who": "mia", "act": "shrug"}]}]
    assert rules.problems(items, SPEAKERS, rules.start, (1, 1)) == []
