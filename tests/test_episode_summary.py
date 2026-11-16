"""StoryOperations.summarize_episode: what an episode told, for the next ones."""

from __future__ import annotations

import json

from kinoforge.segments.story.operations import StoryOperations
from kinoforge.segments.story.ports import StoryPorts

_REC = {
    "input": {"title": "The storm", "language": "en", "conversation": "conv_0123456789abc"},
    "story": {"logline": "a storm", "style": "", "characters": [],
              "scenes": [{"prompt": "sea", "narration": "Ana loses her glasses"}]},
}


class _Ports:
    def __init__(self, reply="Ana lost her glasses — for good.", fail=False) -> None:
        self.reply, self.fail, self.sent = reply, fail, []

    def complete(self, purpose, system, user, *, route, temperature, max_tokens, **turn):
        self.sent.append({"system": system, "user": user, **turn})
        if self.fail:
            raise RuntimeError("down")
        return self.reply, {}

    def ports(self) -> StoryPorts:
        return StoryPorts(
            complete=self.complete, complete_json=None, parse_json=json.loads,
            prompt=lambda key, **p: f"<{key}> {p['title']} {p['scenes']}",
            contract=lambda _n: "", language_rule=lambda *_: "", story_budget=lambda _o=None: 0,
        )


def test_the_summary_is_written_on_the_episode_conversation():
    fake = _Ports()
    out = StoryOperations(fake.ports()).summarize_episode(_REC, {"persona": "P"})
    assert out == {"ok": True, "summary": "Ana lost her glasses, for good."}
    sent = fake.sent[0]
    assert sent["conversation"] == "conv_0123456789abc" and sent["system"] == "P"
    assert sent["user"].startswith("<story_episode_summary> The storm") and "Ana loses" in sent["user"]


def test_no_story_and_a_failed_call_are_refused():
    ops = StoryOperations(_Ports(fail=True).ports())
    assert ops.summarize_episode({"story": {"scenes": []}}, {})["ok"] is False
    failed = ops.summarize_episode(_REC, {"persona": "P"})
    assert failed["ok"] is False and failed["detail"] == "down"
    assert StoryOperations(_Ports(reply="  ").ports()).summarize_episode(_REC, {"persona": "P"})["ok"] is False


def test_an_episode_without_a_conversation_names_none():
    fake = _Ports()
    StoryOperations(fake.ports()).summarize_episode({**_REC, "input": {"title": "t"}}, {"persona": "P"})
    assert "conversation" not in fake.sent[0]
