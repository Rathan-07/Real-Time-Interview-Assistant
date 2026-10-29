"""Per-WebSocket interview session.

A `Session` owns the lifetime of one STT connection + any in-flight LLM
answer task, and forwards typed events back to the browser. The caller
(the WebSocket endpoint) feeds audio in via `feed_audio` and tears down
via `stop`.

Lifecycle invariants:
- Only one answer task is in flight at a time. A new detected question
  cancels the previous task before starting the next one.
- `stop()` is idempotent, bounded, and cancels every background task.
- No `send_text` is attempted after the client disconnects (the inner
  `_send` swallows send errors so we don't leak logs on normal closes).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import WebSocket

from app.models.events import (
    AnswerChunk,
    AnswerComplete,
    ErrorEvent,
    QuestionDetected,
    StatusEvent,
    TranscriptFinal,
    TranscriptInterim,
)
from app.services.llm_service import LLMProvider
from app.services.prompt_builder import AnswerMode, build_prompt
from app.services.question_detector import QuestionDetector
from app.services.stt_service import STTProvider, TranscriptEvent

log = logging.getLogger(__name__)


class Session:
    def __init__(
        self,
        ws: WebSocket,
        stt: STTProvider,
        llm: Optional[LLMProvider] = None,
    ) -> None:
        self._ws = ws
        self._stt = stt
        self._llm = llm
        self._detector = QuestionDetector()

        # SessionStart payload — captured at start, used for prompt-building.
        self._resume: str = ""
        self._job_description: str = ""
        self._mode: AnswerMode = "concise"

        # STT runloop plumbing.
        self._stop_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._conn = None

        # In-flight answer plumbing.
        self._answer_task: asyncio.Task | None = None

        self._stopped = False
        self._open_failed = False

    # ---------------------------------------------------------------- start

    async def start(
        self,
        *,
        resume: str = "",
        job_description: str = "",
        mode: AnswerMode = "concise",
    ) -> bool:
        """Open the STT connection and emit 'listening'. Returns False on failure."""
        self._resume = resume
        self._job_description = job_description
        self._mode = mode

        self._task = asyncio.create_task(self._run(), name="session-run")
        await self._ready_event.wait()
        if self._open_failed:
            return False
        await self._send(StatusEvent(state="listening"))
        return True

    # ---------------------------------------------------------------- audio

    async def feed_audio(self, chunk: bytes) -> None:
        conn = self._conn
        if conn is None or self._stopped:
            return
        try:
            await conn.send_audio(chunk)
        except Exception:
            log.exception("send_audio failed")

    async def ask_manual(self, text: str) -> None:
        """Bypass STT + detector; treat `text` as a confirmed question.

        Lets the UI submit a typed question directly to the LLM pipeline.
        """
        if self._stopped:
            return
        clean = text.strip()
        if not clean:
            return
        qid = f"m_{self._detector._next_id}"  # keep ids disjoint from auto ones
        self._detector._next_id += 1
        log.info("session: manual question id=%s text=%r", qid, clean)
        await self._on_question(qid, clean)

    # ---------------------------------------------------------------- stop

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._detector.reset()

        # Cancel any in-flight answer before tearing down the STT task.
        await self._cancel_answer()

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

    # ---------------------------------------------------------- STT runloop

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
            self._ready_event.set()

    async def _on_transcript(self, evt: TranscriptEvent) -> None:
        if self._stopped:
            return
        if evt.is_final:
            log.info(
                "session: transcript.final text=%r speech_final=%s",
                evt.text,
                evt.speech_final,
            )
            await self._send(
                TranscriptFinal(text=evt.text, speech_final=evt.speech_final)
            )
            detected = self._detector.observe(
                text=evt.text,
                is_final=True,
                speech_final=evt.speech_final,
            )
            if detected is not None:
                await self._on_question(detected.id, detected.text)
        else:
            await self._send(TranscriptInterim(text=evt.text))

    # ---------------------------------------------- question -> answer

    async def _on_question(self, qid: str, text: str) -> None:
        await self._send(QuestionDetected(id=qid, text=text))

        if self._llm is None:
            # STT-only mode (LLM not configured) — emit the question but no answer.
            return

        # Cancel any previous answer that's still streaming — a newer
        # question has arrived and the old answer is stale.
        await self._cancel_answer()

        await self._send(StatusEvent(state="thinking"))
        self._answer_task = asyncio.create_task(
            self._stream_answer(qid, text), name=f"answer-{qid}"
        )

    async def _stream_answer(self, qid: str, question: str) -> None:
        assert self._llm is not None
        payload = build_prompt(
            resume=self._resume,
            job_description=self._job_description,
            question=question,
            mode=self._mode,
        )

        wrote_any = False
        chunk_count = 0
        total_chars = 0
        try:
            async for chunk in self._llm.stream(
                system=payload.system, user=payload.user
            ):
                if not wrote_any:
                    wrote_any = True
                    await self._send(StatusEvent(state="answering"))
                chunk_count += 1
                total_chars += len(chunk)
                await self._send(AnswerChunk(id=qid, text=chunk))

            log.info(
                "answer %s complete: %d chunk(s), %d chars",
                qid,
                chunk_count,
                total_chars,
            )
            await self._send(AnswerComplete(id=qid))
            if not self._stopped:
                await self._send(StatusEvent(state="listening"))
        except asyncio.CancelledError:
            log.info(
                "answer %s CANCELLED after %d chunks / %d chars",
                qid,
                chunk_count,
                total_chars,
            )
            await self._send(AnswerComplete(id=qid))
            raise
        except Exception as e:
            log.exception("LLM stream failed for question %s", qid)
            await self._send(
                ErrorEvent(code="llm_failed", message=type(e).__name__)
            )
            if not self._stopped:
                await self._send(StatusEvent(state="listening"))

    async def _cancel_answer(self) -> None:
        task = self._answer_task
        if task is None or task.done():
            self._answer_task = None
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        self._answer_task = None

    # ---------------------------------------------------------------- send

    async def _send(self, event) -> None:
        try:
            await self._ws.send_text(event.model_dump_json())
        except Exception:
            log.debug("ws send failed", exc_info=True)
