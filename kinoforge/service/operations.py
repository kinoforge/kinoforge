"""Requests that run in the background.

A request naming a callback_url (OperationRequest) is answered at once with 202 and run on a
pool; when it ends its response, or its error, is POSTed to the callback_url and sent again
after growing pauses while the caller cannot take it. An error with status_code 429 means the
gateway took no more of the tenant's calls for now: the caller sends it again later. The url is the caller's: kinoforge holds
no secret for it.
"""

from __future__ import annotations

import contextvars
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from kinoforge.inference.infrelay import InfrelayError, InfrelayLimited
from kinoforge.observ import active
from kinoforge.schemas import OperationAccepted, OperationRequest


class Operations:
    # What an endpoint that may run in the background documents besides its response.
    RESPONSES: dict[int | str, dict[str, Any]] = {
        202: {"model": OperationAccepted, "description": "Runs in the background."}
    }
    # Seconds before each new try of a callback the caller did not take; given up after.
    PAUSES = (2.0, 10.0, 30.0, 120.0, 600.0)
    _pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="kinoforge-op")
    _http = httpx.Client(timeout=30)

    @classmethod
    def answer(cls, request: OperationRequest, run: Callable[[], dict]) -> Any:
        """The response now, or, with a callback_url, 202 and the response posted later."""
        if not request.callback_url:
            return run()
        context = contextvars.copy_context()
        cls._pool.submit(context.run, cls._run, request.callback_url, run)
        return JSONResponse(status_code=202, content={"status": "accepted"})

    @classmethod
    def _run(cls, url: str, run: Callable[[], dict]) -> None:
        try:
            outcome = {"status": "done", "result": jsonable_encoder(run())}
        except HTTPException as exc:
            outcome = {"status": "error", "error": str(exc.detail), "status_code": exc.status_code}
        except InfrelayError as exc:
            status = 429 if isinstance(exc, InfrelayLimited) else 502
            outcome = {"status": "error", "error": str(exc), "status_code": status}
        except Exception as exc:  # noqa: BLE001 - the caller hears of every failure
            active().warning(f"background request failed: {exc}")
            outcome = {"status": "error", "error": str(exc) or type(exc).__name__}
        cls._post(url, outcome)

    @classmethod
    def _post(cls, url: str, body: dict) -> None:
        raw = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        for pause in (0.0, *cls.PAUSES):
            time.sleep(pause)
            try:
                response = cls._http.post(url, content=raw, headers=headers)
            except httpx.HTTPError as exc:
                active().warning(f"background request callback failed: {exc}")
                continue
            if response.status_code < 500:
                return
            active().warning(f"background request callback answered {response.status_code}")
        active().error("gave up calling back a background request")
