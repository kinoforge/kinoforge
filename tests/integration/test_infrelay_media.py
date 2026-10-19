"""InfrelayClient reads generated media wherever a result points: inline bytes, the gateway's
own /media link (from its root) or a provider's link (Infrelay-lite)."""

from __future__ import annotations

import base64

import pytest

httpx = pytest.importorskip("httpx")

from kinoforge.inference.infrelay import InfrelayClient  # noqa: E402


def _result(kind: str, value: str) -> dict:
    return {"output": {"type": kind, "value": value}}


def test_media_links_resolve_against_the_gateway(monkeypatch):
    asked = []

    def handle(request):
        asked.append(str(request.url))
        return httpx.Response(200, content=b"clip")

    monkeypatch.setattr(InfrelayClient, "_http", httpx.Client(transport=httpx.MockTransport(handle)))
    client = InfrelayClient("http://infrelay:8090/")

    assert client._bytes(_result("url", "/media/job-1.mp4?sig=abc")) == b"clip"
    assert client._bytes(_result("url", "https://fal.media/x.mp4")) == b"clip"
    assert client._bytes(_result("b64", base64.b64encode(b"inline").decode())) == b"inline"
    assert asked == ["http://infrelay:8090/media/job-1.mp4?sig=abc", "https://fal.media/x.mp4"]
