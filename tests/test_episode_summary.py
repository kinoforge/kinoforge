from __future__ import annotations

import json

from kinoforge.segments.story.operations import StoryOperations
from kinoforge.segments.story.ports import StoryPorts

DASH = chr(0x2014)

_REC = {
    "input": {"title": "The storm", "language": "en", "conversation": "conv_0123456789abc"},
    "story": {"logline": "a storm", "style": "", "characters": [],
              "scenes": [{"prompt": "Ana on the pier", "narration": "Ana loses her glasses"}]},
}
_CAST = [{"name": "Ana", "look": "girl, curly hair", "wears": "round glasses, yellow coat"},
         {"name": "Leo", "look": "boy, short hair", "wears": ""}]
_ANSWER = {"summary": f"Ana lost her glasses {DASH} for good.",
           "cast": [{"name": "Ana", "look": "", "wears": "yellow coat"}, {"look": "nameless"}]}


class _Ports:
    def __init__(self, reply=json.dumps(_ANSWER), fail=False) -> None:
        self.reply, self.fail, self.sent, self.values = reply, fail, [], {}

    def complete(self, purpose, system, user, *, route, temperature, max_tokens, **turn):
        self.sent.append({"system": system, "user": user, **turn})
        if self.fail:
            raise RuntimeError("down")
        return self.reply, {}

    def prompt(self, key, **values):
        self.values = values
        return f"<{key}> {values['title']} {values['scenes']}"

    def ports(self) -> StoryPorts:
        return StoryPorts(
            complete=self.complete, complete_json=None, parse_json=json.loads,
            prompt=self.prompt,
            contract=lambda _n: "", language_rule=lambda *_: "", story_budget=lambda _o=None: 0,
        )


def test_the_summary_and_the_cast_changes_are_written_on_the_episode_conversation():
    fake = _Ports()
    out = StoryOperations(fake.ports()).summarize_episode(_REC, {"persona": "P"}, cast=_CAST)
    assert out == {"ok": True, "summary": "Ana lost her glasses, for good.",
                   "cast": [{"name": "Ana", "look": "", "wears": "yellow coat"}]}
    sent = fake.sent[0]
    assert sent["conversation"] == "conv_0123456789abc" and sent["system"] == "P"
    assert sent["user"].startswith("<story_episode_summary> The storm") and "Ana loses" in sent["user"]
    assert "Shown: Ana on the pier" in fake.values["scenes"]
    assert fake.values["cast"] == (
        "- Ana. Identity: girl, curly hair State: round glasses, yellow coat\n"
        "- Leo. Identity: boy, short hair State: not given"
    )


def test_no_story_a_failed_call_and_an_unreadable_answer_are_refused():
    ops = StoryOperations(_Ports(fail=True).ports())
    assert ops.summarize_episode({"story": {"scenes": []}}, {})["ok"] is False
    failed = ops.summarize_episode(_REC, {"persona": "P"})
    assert failed["ok"] is False and failed["detail"] == "down"
    for reply in ("  ", "Ana lost her glasses.", json.dumps({"summary": " ", "cast": []})):
        out = StoryOperations(_Ports(reply=reply).ports()).summarize_episode(_REC, {"persona": "P"})
        assert out["ok"] is False


def test_an_episode_without_a_conversation_names_none_and_no_cast_reads_none():
    fake = _Ports()
    StoryOperations(fake.ports()).summarize_episode({**_REC, "input": {"title": "t"}}, {"persona": "P"})
    assert "conversation" not in fake.sent[0]
    assert fake.values["cast"] == "none"
