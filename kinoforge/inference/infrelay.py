from __future__ import annotations

import base64
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin

import httpx

from kinoforge.contract import AITask, ImageSpec, ModelRef, VideoSpec
from kinoforge.inference.charges import InferenceCharges
from kinoforge.observ import active, shape


class InfrelayError(RuntimeError):
    pass


class InfrelayLimited(InfrelayError):
    """Infrelay took no more of this tenant's calls for now (429): send it again once earlier
    ones end."""


class InfrelayClient:
    """Client for the Infrelay POST /v1/inference/{task} contract (cloud Infrelay or
    Infrelay-lite). Every call names its task; the pick says which model (or `auto`). A call
    past Infrelay's timeout is read again at the link its 504 names until it ends."""

    # One connection pool for every call, so a story's many calls reuse warm connections
    # instead of paying a TCP and TLS handshake each.
    _http = httpx.Client(limits=httpx.Limits(max_connections=64, max_keepalive_connections=16))
    # Seconds between reads of a late answer when Infrelay does not say (Retry-After).
    READ_EVERY = 2.0
    # The only links a late answer is read at, so the token goes nowhere else.
    LATE_LINK = "/v1/requests/"

    def __init__(self, url: str, token: str = "", tenant: str = "") -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._tenant = tenant
        # Prompt rewrites infrelay ran for this client's calls, for the caller to bill.
        self.rewrites: List[Dict[str, Any]] = []
        # The provider and model that answered the last call; an auto pick only learns them
        # from the answer.
        self.served: Dict[str, str] = {}

    def _body(self, ref: ModelRef, payload: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {"inference": ref.inference(), "input": payload}
        if self._tenant:
            body["tenant_id"] = self._tenant
        return body

    def _infer(
        self, task: AITask, ref: ModelRef, payload: Dict[str, Any], *, timeout: float
    ) -> Dict[str, Any]:
        log = active()
        if not self._url:
            raise InfrelayError("INFRELAY_URL is required")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        url = f"{self._url}/v1/inference/{task.value}"
        log.debug(f"infrelay -> {task} {ref}", task=task.value, route=str(ref),
                  tenant=self._tenant or None, url=url, timeout=timeout,
                  payload=shape(payload, max_depth=2))
        log.trace(f"infrelay {task} input", **shape(payload, max_depth=1))
        started = time.monotonic()
        response = self._admitted(task, ref, url, headers, payload, started + timeout)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        late = response.status_code == 504 and "retry_url" in response.text
        if late:
            log.debug(f"infrelay {task} {ref} answers late: reading its link", ms=elapsed_ms)
            result = self._late(response.json(), started + timeout)
        elif response.status_code >= 400:
            log.warning(f"infrelay {task} {ref} failed ({response.status_code}) in {elapsed_ms}ms",
                        status=response.status_code, body=response.text[:300])
            raise InfrelayError(
                f"infrelay {task} {ref} failed ({response.status_code}): {response.text[:300]}"
            )
        else:
            result = response.json()
        self._answered(task, ref, result)
        log.debug(f"infrelay <- {task} {ref} {response.status_code} in {elapsed_ms}ms",
                  status=response.status_code, ms=elapsed_ms, served=self.served,
                  output_type=(result.get("output") or {}).get("type"),
                  request_id=result.get("request_id"))
        return result

    def _admitted(
        self, task: AITask, ref: ModelRef, url: str, headers: Dict[str, str],
        payload: Dict[str, Any], deadline: float,
    ) -> httpx.Response:
        """Infrelay's answer to the call. While it takes no more of the tenant's calls (429)
        the call is sent again after its Retry-After, until the deadline; past it the call is
        InfrelayLimited."""
        while True:
            try:
                response = self._http.post(
                    url, headers=headers, json=self._body(ref, payload),
                    timeout=max(1.0, deadline - time.monotonic()),
                )
            except httpx.HTTPError as exc:
                active().warning(f"infrelay {task} {ref} unreachable: {exc}")
                raise InfrelayError(f"infrelay {task} {ref} unreachable: {exc}") from exc
            if response.status_code != 429:
                return response
            wait = float(response.headers.get("Retry-After") or self.READ_EVERY)
            if time.monotonic() + wait > deadline:
                raise InfrelayLimited(f"infrelay {task} {ref}: {response.text[:300]}")
            active().debug(f"infrelay {task} {ref} is full for this tenant: again in {wait}s")
            time.sleep(wait)

    def _answered(self, task: AITask, ref: ModelRef, result: Dict[str, Any]) -> None:
        """Notes who served a call, what it cost (for the caller to bill) and its rewrite."""
        usage = result.get("usage") or {}
        self.served = {
            "provider": str(result.get("provider") or ref.provider),
            "model": str(result.get("model") or ref.model),
        }
        InferenceCharges.add({
            "task": task.value,
            "kind": str(result.get("kind") or ""),
            **self.served,
            "credits": int(usage.get("credits") or 0),
            "byok": bool(usage.get("byok")),
            "units": int(usage.get("units") or 1),
        })
        rewrite = usage.get("enhance")
        if isinstance(rewrite, dict):
            self.rewrites.append(dict(rewrite))

    def _late(self, late: Dict[str, Any], deadline: float) -> Dict[str, Any]:
        """A direct call's answer read at the link Infrelay's 504 named, until it ends or the
        deadline passes."""
        link = str(late["retry_url"])
        if not link.startswith(self.LATE_LINK) or "@" in link:
            raise InfrelayError(f"infrelay named an unexpected answer link: {link[:100]}")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        while True:
            try:
                response = self._http.get(f"{self._url}{link}", headers=headers, timeout=60)
            except httpx.HTTPError as exc:
                raise InfrelayError(f"infrelay unreachable reading {link}: {exc}") from exc
            if response.status_code == 200:
                return response.json()
            if response.status_code not in (202, 429):
                raise InfrelayError(
                    f"infrelay {link} failed ({response.status_code}): {response.text[:300]}"
                )
            wait = float(response.headers.get("Retry-After") or self.READ_EVERY)
            if time.monotonic() + wait > deadline:
                raise InfrelayError(f"infrelay {link} did not answer in time")
            time.sleep(wait)

    def text(
        self, task: AITask, ref: ModelRef, system: str, user: str, *, temperature: float,
        max_tokens: int,
    ) -> Tuple[str, Dict]:
        """One chat completion: (text, usage). Usage carries model, token counts and
        finish_reason so a stage runner can detect a cut-off answer."""
        output = self._chat(task, ref, system, user, temperature, max_tokens)["output"]
        return str(output.get("value") or ""), dict(output.get("meta") or {})

    def complete(self, task: AITask, ref: ModelRef, prompt: str, *, max_tokens: int,
                 temperature: float, system: str = "") -> Tuple[str, ModelRef]:
        """One chat completion: the text, and the provider and model that served it."""
        result = self._chat(task, ref, system, prompt, temperature, max_tokens)
        served = ModelRef(str(result.get("provider") or ""), str(result.get("model") or ""))
        return str(result["output"].get("value") or ""), served

    def _chat(self, task: AITask, ref: ModelRef, system: str, user: str, temperature: float,
              max_tokens: int) -> Dict[str, Any]:
        payload = {"system": system, "user": user,
                   "temperature": temperature, "max_tokens": max_tokens}
        result = self._infer(task, ref, payload, timeout=300)
        if (result.get("output") or {}).get("type") != "text":
            raise InfrelayError("infrelay text returned unsupported output")
        return result

    def image(self, task: AITask, ref: ModelRef, prompt: str, spec: ImageSpec) -> bytes:
        payload: Dict[str, Any] = {
            "prompt": prompt, "aspect_ratio": spec.aspect_ratio, "safe": not spec.mature,
        }
        if spec.seed is not None:
            payload["seed"] = int(spec.seed)
        if spec.negative:
            payload["negative"] = spec.negative
        if spec.reference is not None:
            payload["reference_b64"] = base64.b64encode(spec.reference).decode()
        self._add_enhance(payload, spec.enhance, spec.enhance_style)
        return self._bytes(self._infer(task, ref, payload, timeout=1000))

    def video(self, task: AITask, ref: ModelRef, prompt: str, spec: VideoSpec) -> bytes:
        """Video (mp4) bytes. A native-audio model voices `dialogue` itself, said on camera by
        `speaker` when one is named; `music` toggles a non-diegetic score. Providers without
        their own audio ignore all three."""
        payload = self._video_payload(prompt, spec)
        return self._bytes(self._infer(task, ref, payload, timeout=1800))

    def submit_video(
        self, task: AITask, ref: ModelRef, prompt: str, spec: VideoSpec, callback_url: str
    ) -> str:
        """Queues a clip on infrelay and returns its job id at once. Infrelay posts the job to
        `callback_url` when it ends; read it with job and job_media."""
        body = self._body(ref, self._video_payload(prompt, spec))
        body["callback_url"] = callback_url
        job = self._jobs("POST", f"/v1/inference/{task.value}", body=body)
        active().debug(f"infrelay queued video {ref}", job=job.get("id"), status=job.get("status"))
        return str(job["id"])

    def job(self, job_id: str) -> Dict[str, Any]:
        return self._jobs("GET", f"/v1/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        return self._jobs("DELETE", f"/v1/jobs/{job_id}")

    def job_media(self, job: Dict[str, Any]) -> Tuple[str, bytes]:
        """A finished job's media: the key the gateway stored it at (no bytes are fetched), or
        its bytes when it was not stored; what it cost and its prompt rewrite are kept for the
        caller to bill."""
        result = job.get("result") or {}
        task = AITask(str(job.get("task") or result.get("task") or job.get("kind") or "video"))
        self._answered(task, ModelRef(str(job.get("provider") or ""), str(job.get("model") or "")),
                       result)
        stored = str(result.get("stored") or "")
        return (stored, b"") if stored else ("", self._bytes(result))

    def _jobs(
        self, method: str, path: str, *, body: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        if not self._url:
            raise InfrelayError("INFRELAY_URL is required")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            response = self._http.request(method, f"{self._url}{path}", headers=headers,
                                          json=body, timeout=60)
        except httpx.HTTPError as exc:
            raise InfrelayError(f"infrelay jobs unreachable: {exc}") from exc
        failed = InfrelayLimited if response.status_code == 429 else InfrelayError
        if response.status_code >= 400:
            raise failed(
                f"infrelay job {method} failed ({response.status_code}): {response.text[:300]}"
            )
        return response.json()

    def _video_payload(self, prompt: str, spec: VideoSpec) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "prompt": prompt, "seconds": spec.seconds, "resolution": spec.resolution,
            "aspect_ratio": spec.aspect_ratio, "safe": not spec.mature,
        }
        if spec.image is not None:
            payload["reference_b64"] = base64.b64encode(spec.image).decode()
        if spec.references:
            payload["ref_images_b64"] = [base64.b64encode(ref).decode() for ref in spec.references]
        self._add_enhance(payload, spec.enhance, spec.enhance_style)
        if spec.dialogue:
            payload["dialogue"] = spec.dialogue
            if spec.speaker:
                payload["speaker"] = spec.speaker
        if not spec.music:
            payload["music"] = False
        return payload

    def music(self, task: AITask, ref: ModelRef, prompt: str, *, seconds: int = 30) -> bytes:
        payload: Dict[str, Any] = {"prompt": prompt, "seconds": seconds}
        return self._bytes(self._infer(task, ref, payload, timeout=1800))

    def speech(self, task: AITask, ref: ModelRef, text: str, *, voice: str = "",
               language: str = "") -> bytes:
        payload: Dict[str, Any] = {"text": text}
        if voice:
            payload["voice"] = voice
        if language:
            payload["language"] = language
        return self._bytes(self._infer(task, ref, payload, timeout=600))

    def transcribe(self, task: AITask, audio: bytes, ref: ModelRef,
                   **kwargs: Any) -> Tuple[List[Dict], Dict]:
        payload: Dict[str, Any] = {"audio_b64": base64.b64encode(audio).decode()}
        if kwargs.get("language"):
            payload["language"] = kwargs["language"]
        if kwargs.get("word_timestamps"):
            payload["word_timestamps"] = True
        params = kwargs.get("params") or {}
        payload.update({key: value for key, value in params.items() if value is not None})
        output = self._infer(task, ref, payload, timeout=1800).get("output") or {}
        if output.get("type") != "transcript":
            raise InfrelayError("infrelay transcribe returned unsupported output")
        meta = output.get("meta") or {}
        return list(meta.get("segments") or []), meta

    @staticmethod
    def _add_enhance(payload: Dict[str, Any], enhance: bool, style: str) -> None:
        if enhance:
            payload["enhance"] = True
            if style:
                payload["enhance_style"] = style

    def _bytes(self, result: Dict[str, Any]) -> bytes:
        """The media a result carries; a link from the gateway's own root is read from it."""
        output = result.get("output") or {}
        kind = output.get("type")
        if kind == "b64":
            return base64.b64decode(output["value"])
        if kind == "url":
            url = urljoin(f"{self._url}/", str(output["value"]))
            try:
                response = InfrelayClient._http.get(url, timeout=600, follow_redirects=True)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise InfrelayError(f"could not fetch generated media: {exc}") from exc
            return response.content
        raise InfrelayError(f"infrelay returned unsupported output type: {kind}")
