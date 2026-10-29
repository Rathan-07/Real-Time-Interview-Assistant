"""Per-WebSocket interview session.

A `Session` owns the lifetime of one STT provider connection and forwards
transcript events back to the browser as typed JSON. The caller (the
WebSocket endpoint) feeds audio in via `feed_audio` and tears down via `stop`.

Shutdown invariant: no matter who closes first — client disconnect, explicit
Stop, or an STT failure — `stop()` cancels background tasks and closes the
provider connection exactly once.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

from app.models.events import (
    ErrorEvent,
    StatusEvent,
    TranscriptFinal,
    TranscriptInterim,
)
from app.services.stt_service import STTProvider, TranscriptEvent

log = logging.getLogger(__name__)


class Session:
    def __init__(self, ws: WebSocket, stt: STTProvider) -> None:
        self._ws = ws
        self._stt = stt
        self._stop_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._conn = None
        self._stopped = False
        self._open_failed = False

    async def start(self) -> bool:
        """Open the STT connection and emit 'listening'. Returns False on failure."""
        self._task = asyncio.create_task(self._run(), name="session-run")
        await self._ready_event.wait()
        if self._open_failed:
            return False
        await self._send(StatusEvent(state="listening"))
        return True

    async def feed_audio(self, chunk: bytes) -> None:
        conn = self._conn
        if conn is None or self._stopped:
            return
        try:
            await conn.send_audio(chunk)
        except Exception:
            log.exception("send_audio failed")

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except asyncio.TimeoutError:
                log.warning("session task did not exit in time; cancelling")
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
            except Exception:
                log.exception("session task raised during shutdown")
        await self._send(StatusEvent(state="stopped"))

    async def _run(self) -> None:
        try:
            async with self._stt.open(self._on_transcript) as conn:
                self._conn = conn
                self._ready_event.set()
                await self._stop_event.wait()
        except Exception as e:
            log.exception("stt session failed to open or crashed")
            self._open_failed = True
            await self._send(
                ErrorEvent(code="stt_failed", message=type(e).__name__)
            )
        finally:
            self._conn = None
            # Unblock start() in case the context manager raised before yielding.
            self._ready_event.set()

    async def _on_transcript(self, evt: TranscriptEvent) -> None:
        if self._stopped:
            return
        if evt.is_final:
            await self._send(
                TranscriptFinal(text=evt.text, speech_final=evt.speech_final)
            )
        else:
            await self._send(TranscriptInterim(text=evt.text))

    async def _send(self, event) -> None:
        try:
            await self._ws.send_text(event.model_dump_json())
        except Exception:
            # The client likely disconnected mid-emit; log at debug.
            log.debug("ws send failed", exc_info=True)
