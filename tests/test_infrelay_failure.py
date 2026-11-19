import httpx

from kinoforge.inference.infrelay import InfrelayError
from kinoforge.segments.story.agent import ModelFailure


def test_a_failed_answer_keeps_the_failure_class_infrelay_named():
    response = httpx.Response(502, json={"detail": "model said no", "failure": "refused"})
    error = InfrelayError.answered("infrelay image.generate", response)

    assert error.failure == "refused" and "model said no" in str(error)
    assert ModelFailure.of("Cast image", error)["failure"] == "refused"


def test_an_answer_without_a_class_names_none():
    error = InfrelayError.answered("infrelay text", httpx.Response(502, text="bad gateway"))

    assert error.failure == ""
    assert "failure" not in ModelFailure.of("Story", error)
