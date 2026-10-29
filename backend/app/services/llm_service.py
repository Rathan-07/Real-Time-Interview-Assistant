"""Streaming LLM adapters.

Same Protocol-based shape as stt_service.py. Everything downstream only
depends on `LLMProvider.stream()` yielding string chunks — the Session,
tests, and websocket code have no idea which provider is behind it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Protocol, Sequence

log = logging.getLogger(__name__)


class LLMProvider(Protocol):
    def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        """Yield incremental text chunks for an answer. Caller is responsible
        for assembling and for cancelling the iterator if the answer is stale."""
        ...


# ----------------------- Gemini implementation ------------------------


class GeminiStreamingProvider:
    """Thin wrapper around google-genai 2.34's AsyncClient.

    One Provider per app (holds api_key + model). Each call to `stream()`
    opens a new streaming request; cancellation is handled by the caller
    (Session) via standard asyncio Task.cancel().

    Timeouts:
    - `connect_timeout_s` bounds the time to send the request and receive
      the first streaming chunk (defends against stuck requests, DNS hangs,
      and model-not-found retry storms where the SDK quietly retries 404s).
    - `chunk_timeout_s` bounds the gap between consecutive chunks once the
      stream is active (defends against half-closed TCP connections).
    Overall wall-clock is implicitly bounded by max_output_tokens too.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int = 600,
        temperature: float = 0.3,
        connect_timeout_s: float = 20.0,
        # Generous between-chunk cap. Gemini "flash" models usually deliver
        # the first chunk inside 2 s, but Google occasionally takes 10-15 s
        # to spool up under load (we've seen 503s on this same path). 20 s
        # keeps the UI responsive without surfacing a false-positive error
        # for a transient slow start.
        chunk_timeout_s: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._connect_timeout_s = connect_timeout_s
        self._chunk_timeout_s = chunk_timeout_s

    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        # Deferred import so unit tests that only use FakeLLMProvider don't
        # need the SDK loaded.
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
        )

        iterator = None
        last_exc: Exception | None = None
        # Google occasionally returns 503 UNAVAILABLE under capacity spikes.
        # The SDK does some internal retrying but can still surface a 503 to
        # us. One short extra retry handles a demo-time blip without turning
        # it into a user-visible error.
        for attempt in range(2):
            try:
                iterator = await asyncio.wait_for(
                    client.aio.models.generate_content_stream(
                        model=self._model,
                        contents=user,
                        config=config,
                    ),
                    timeout=self._connect_timeout_s,
                )
                break
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"Gemini did not respond within {self._connect_timeout_s}s"
                    f" (model={self._model!r})"
                ) from exc
            except Exception as exc:
                last_exc = exc
                # Retry only on 5xx (transient server-side), not 4xx (our bug).
                is_transient = "503" in str(exc) or "UNAVAILABLE" in str(exc)
                if attempt == 0 and is_transient:
                    log.warning(
                        "gemini transient %s — retrying in 1s", type(exc).__name__
                    )
                    await asyncio.sleep(1.0)
                    continue
                raise
        if iterator is None:
            # Shouldn't reach here, but mypy appreciates the guard.
            assert last_exc is not None
            raise last_exc

        async def _next() -> "object | None":
            # Sentinel-returning helper so we can wrap each step in wait_for.
            try:
                return await iterator.__anext__()
            except StopAsyncIteration:
                return _SENTINEL_DONE

        while True:
            try:
                response = await asyncio.wait_for(
                    _next(), timeout=self._chunk_timeout_s
                )
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"Gemini stalled mid-stream (>{self._chunk_timeout_s}s"
                    f" between chunks)"
                ) from exc
            if response is _SENTINEL_DONE:
                return
            text = getattr(response, "text", None)
            if text:
                yield text


_SENTINEL_DONE = object()


# --------------------------- Fake for tests ---------------------------


class FakeLLMProvider:
    """Yields a pre-scripted sequence of chunks with configurable per-chunk
    delays. Used by tests to verify streaming and cancellation behavior
    without a real Gemini call."""

    def __init__(
        self,
        chunks: Sequence[str],
        per_chunk_delay_s: float = 0.01,
    ) -> None:
        self._chunks = list(chunks)
        self._delay = per_chunk_delay_s

    async def stream(self, *, system: str, user: str) -> AsyncIterator[str]:
        for chunk in self._chunks:
            await asyncio.sleep(self._delay)
            yield chunk
