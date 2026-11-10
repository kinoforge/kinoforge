from kinoforge.contract import ShotStart


def test_shot_start_keeps_only_known_answers():
    assert ShotStart.of("cut") == "cut"
    assert ShotStart.of(" Continue ") == "continue"
    assert ShotStart.of("dissolve") == ""
    assert ShotStart.of(None) == ""


def test_the_shot_plan_lists_the_length_a_scene_asks_for():
    from kinoforge.segments.story.operations import StoryOperations
    from kinoforge.segments.story.ports import StoryPorts

    sent: dict = {}

    def prompt(key, **params):
        sent.update(params)
        return key

    ports = StoryPorts(
        complete=None, parse_json=None, contract=None, language_rule=None, story_budget=None,
        prompt=prompt, complete_json=lambda *_a, **_k: {"shots": [{"action": "a"}, {"action": "b"}]},
    )
    scenes = [{"prompt": "p1", "seconds": 14}, {"prompt": "p2", "seconds": "x"}]
    StoryOperations(ports).direct_shots({"story": {"scenes": scenes}})

    assert "LENGTH: 14 seconds" in sent["scenes"]
    assert sent["scenes"].count("LENGTH") == 1
