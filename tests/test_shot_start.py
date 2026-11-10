from kinoforge.contract import ShotStart


def test_shot_start_keeps_only_known_answers():
    assert ShotStart.of("cut") == "cut"
    assert ShotStart.of(" Continue ") == "continue"
    assert ShotStart.of("dissolve") == ""
    assert ShotStart.of(None) == ""
