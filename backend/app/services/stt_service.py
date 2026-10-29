"""Streaming speech-to-text adapters.

Everything the rest of the app consumes lives behind two small Protocols:

- STTProvider.open(on_transcript) -> async context manager yielding STTConnection
- STTConnection.send_audio(bytes) / aclose()

The Deepgram implementation lives alongside a FakeSTTProvider used by tests.
Swapping to AssemblyAI or Whisper later means writing one more adapter.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import (
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Callable,
    Protocol,
    Sequence,
    Tuple,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptEvent:
    text: str
    is_final: bool
    speech_final: bool = False
    start: float = 0.0
    duration: float = 0.0


OnTranscript = Callable[[TranscriptEvent], Awaitable[None]]


class STTConnection(Protocol):
    async def send_audio(self, chunk: bytes) -> None: ...
    async def aclose(self) -> None: ...


class STTProvider(Protocol):
    def open(
        self, on_transcript: OnTranscript
    ) -> AsyncContextManager[STTConnection]: ...


# ------------------------- Deepgram implementation -------------------------


class DeepgramLiveProvider:
    """Thin wrapper around deepgram-sdk v7's AsyncDeepgramClient."""

    def __init__(
        self,
        api_key: str,
        model: str,
        interim_silence_ms: int,
        language: str = "en",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._silence_ms = interim_silence_ms
        self._language = language

    @asynccontextmanager
    async def open(
        self, on_transcript: OnTranscript
    ) -> AsyncIterator[STTConnection]:
        # Imports deferred so tests that only use FakeSTT don't need the SDK.
        from deepgram import AsyncDeepgramClient
        from deepgram.listen.v1.types.listen_v1results import ListenV1Results
        from deepgram.listen.v1.types.listen_v1utterance_end import (
            ListenV1UtteranceEnd,
        )

        log.info(
            "deepgram: opening session (model=%s, language=%s, endpointing=%dms)",
            self._model,
            self._language,
            self._silence_ms,
        )
        client = AsyncDeepgramClient(api_key=self._api_key)

        async with client.listen.v1.connect(
            model=self._model,
            language=self._language,
            interim_results=True,
            smart_format=True,
            punctuate=True,
            # endpointing: ms of silence before Deepgram ends a transcript
            # with speech_final=True on its NEXT Results message. In practice
            # this signal is unreliable — if the client stops streaming audio
            # or the user falls silent abruptly, speech_final may never arrive.
            endpointing=self._silence_ms,
            # utterance_end_ms: Deepgram sends a SEPARATE UtteranceEnd event
            # after this much silence, independent of Results messages. This
            # is the deterministic end-of-utterance signal we actually trust.
            utterance_end_ms=max(1000, self._silence_ms),
            # No encoding/sample_rate for containerized formats (WebM/Opus).
        ) as socket:

            async def _pump() -> None:
                try:
                    async for msg in socket:
                        # UtteranceEnd is the reliable end-of-speech signal.
                        # Emit a synthetic flush event with no new text so the
                        # question detector collapses its buffer and decides.
                        if isinstance(msg, ListenV1UtteranceEnd):
                            await on_transcript(
                                TranscriptEvent(
                                    text="",
                                    is_final=True,
                                    speech_final=True,
                                )
                            )
                            continue
                        if not isinstance(msg, ListenV1Results):
                            continue
                        if msg.channel is None or not msg.channel.alternatives:
                            continue
                        alt = msg.channel.alternatives[0]
                        text = (alt.transcript or "").strip()
                        if not text:
                            continue
                        await on_transcript(
                            TranscriptEvent(
                                text=text,
                                is_final=bool(msg.is_final),
                                speech_final=bool(msg.speech_final),
                                start=float(msg.start or 0.0),
                                duration=float(msg.duration or 0.0),
                            )
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("deepgram recv loop crashed")

            pump_task = asyncio.create_task(_pump(), name="deepgram-recv")

            class _Conn:
                async def send_audio(self, chunk: bytes) -> None:
                    await socket.send_media(chunk)

                async def aclose(self) -> None:
                    try:
                        await socket.send_close_stream()
                    except Exception:
                        log.debug("send_close_stream failed", exc_info=True)

            try:
                yield _Conn()
            finally:
                pump_task.cancel()
                try:
                    await pump_task
                except asyncio.CancelledError:
                    pass


# --------------------------- Fake for tests --------------------------------

ScriptStep = Tuple[float, TranscriptEvent]  # (delay_seconds, event)


class FakeSTTProvider:
    """Deterministic STT for pytest.

    `script` is a sequence of (delay, event) pairs. The fake sleeps for `delay`
    and emits the event, in order. Audio sent via send_audio is discarded.
    """

    def __init__(self, script: Sequence[ScriptStep]) -> None:
        self._script = list(script)

    @asynccontextmanager
    async def open(
        self, on_transcript: OnTranscript
    ) -> AsyncIterator[STTConnection]:
        async def _play() -> None:
            try:
                for delay, evt in self._script:
                    await asyncio.sleep(delay)
                    await on_transcript(evt)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_play(), name="fake-stt-play")

        class _Conn:
            async def send_audio(self, chunk: bytes) -> None:
                return

            async def aclose(self) -> None:
                return

        try:
            yield _Conn()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
