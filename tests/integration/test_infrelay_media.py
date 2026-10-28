"""InfrelayClient reads generated media wherever a result points: inline bytes, the gateway's
own /media link (from its root) or a provider's link (Infrelay-lite)."""

from __future__ import annotations

import base64
import time

import pytest

httpx = pytest.importorskip("httpx")

from kinoforge.contract import MediaFile, VideoSpec  # noqa: E402
from kinoforge.inference.infrelay import InfrelayClient  # noqa: E402


def _result(kind: str, value: str) -> dict:
    return {"output": {"type": kind, "value": value}}


def test_media_links_resolve_against_the_gateway(monkeypatch):
    asked = []

    def handle(request):
        asked.append(str(request.url))
        return httpx.Response(200, content=b"clip")

    monkeypatch.setattr(
        InfrelayClient, "_http", httpx.Client(transport=httpx.MockTransport(handle))
    )
    client = InfrelayClient("http://infrelay:8090/")

    assert client._bytes(_result("url", "/media/job-1.mp4?sig=abc")) == b"clip"
    assert client._bytes(_result("url", "https://fal.media/x.mp4")) == b"clip"
    assert client._bytes(_result("b64", base64.b64encode(b"inline").decode())) == b"inline"
    assert asked == ["http://infrelay:8090/media/job-1.mp4?sig=abc", "https://fal.media/x.mp4"]


def test_a_gateway_that_takes_no_more_calls_for_now_says_limited(monkeypatch):
    from kinoforge.contract import AITask, ModelRef
    from kinoforge.inference.infrelay import InfrelayLimited
    from kinoforge.service.operations import Operations

    full = httpx.Response(429, json={"detail": "requests are limited to 5 waiting at a time"})
    monkeypatch.setattr(
        InfrelayClient, "_http", httpx.Client(transport=httpx.MockTransport(lambda _r: full))
    )
    client = InfrelayClient("http://infrelay:8090")
    posted: list[dict] = []
    monkeypatch.setattr(
        Operations, "_post", classmethod(lambda cls, url, body: posted.append(body))
    )

    with pytest.raises(InfrelayLimited):  # a clip waits with its caller (core), not here
        client.submit_video(AITask.VIDEO, ModelRef("fal", "x"), "rain", _spec(), "http://core/cb")
    # A call still refused at its deadline ends limited.
    Operations._run(
        "http://core/cb",
        lambda: client._infer(AITask.TEXT, ModelRef("openrouter", "m"), {"user": "hi"}, timeout=0),
    )

    assert posted[0]["status"] == "error" and posted[0]["status_code"] == 429


def test_a_call_the_gateway_is_full_for_is_sent_again_once_it_has_room(monkeypatch):
    from kinoforge.contract import AITask, ModelRef

    replies = [
        httpx.Response(429, json={"detail": "full"}, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"output": {"type": "text", "value": "a story"}}),
    ]
    monkeypatch.setattr(
        InfrelayClient,
        "_http",
        httpx.Client(transport=httpx.MockTransport(lambda _r: replies.pop(0))),
    )
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    text, _ = InfrelayClient("http://infrelay:8090").complete(
        AITask.TEXT, ModelRef("openrouter", "m"), "hi", max_tokens=10, temperature=0.5
    )

    assert (text, slept) == ("a story", [1.0])


def _spec():
    from kinoforge.contract import VideoSpec

    return VideoSpec(seconds=5, resolution=720, aspect_ratio="9:16")


def test_a_clip_that_ends_on_a_still_sends_it_as_the_last_frame():
    client = InfrelayClient("http://infrelay:8090/")
    linked = VideoSpec(seconds=12, resolution=720, aspect_ratio="9:16",
                       image=MediaFile(url="https://assets/start"),
                       last_frame=MediaFile(url="https://assets/end"))
    inline = VideoSpec(seconds=12, resolution=720, aspect_ratio="9:16",
                       last_frame=MediaFile(data=b"end"))

    sent = client._video_payload("p", linked)
    assert (sent["reference_url"], sent["last_frame_url"]) == (
        "https://assets/start", "https://assets/end"
    )
    assert client._video_payload("p", inline)["last_frame_b64"] == base64.b64encode(b"end").decode()
    assert "last_frame_b64" not in client._video_payload("p", VideoSpec(5, 720, "9:16"))


def test_a_clip_made_to_a_soundtrack_sends_it_as_audio():
    client = InfrelayClient("http://infrelay:8090/")
    linked = VideoSpec(5, 720, "9:16", audio=MediaFile(url="https://assets/line"))
    inline = VideoSpec(5, 720, "9:16", audio=MediaFile(data=b"line"))

    assert client._video_payload("p", linked)["audio_url"] == "https://assets/line"
    assert client._video_payload("p", inline)["audio_b64"] == base64.b64encode(b"line").decode()
    assert "audio_b64" not in client._video_payload("p", VideoSpec(5, 720, "9:16"))
