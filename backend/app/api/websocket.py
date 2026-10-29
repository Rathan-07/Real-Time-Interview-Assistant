from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.deps import get_llm_provider, get_stt_provider
from app.models.events import (
    ErrorEvent,
    QuestionManual,
    SessionStart,
    SessionStop,
    StatusEvent,
    client_event_adapter,
)
from app.services.llm_service import LLMProvider
from app.services.session_manager import Session
from app.services.stt_service import STTProvider

log = logging.getLogger(__name__)
router = APIRouter()

# MediaRecorder at 250 ms produces ~4-16 KB per WebM/Opus chunk. 128 KB is
# ~10x normal and still safely under uvicorn's default WS frame limit.
# A larger frame means the client is misbehaving or compromised; drop it.
MAX_AUDIO_FRAME_BYTES = 128 * 1024


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    stt_provider: Optional[STTProvider] = Depends(get_stt_provider),
    llm_provider: Optional[LLMProvider] = Depends(get_llm_provider),
) -> None:
    await ws.accept()
    await _send(ws, StatusEvent(state="idle", message="connected"))

    session: Session | None = None

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break

            if msg.get("text") is not None:
                session = await _handle_text(
                    ws, msg["text"], session, stt_provider, llm_provider
                )
                if session is None and ws.client_state.name == "DISCONNECTED":
                    break
            elif msg.get("bytes") is not None:
                frame = msg["bytes"]
                if len(frame) > MAX_AUDIO_FRAME_BYTES:
                    log.warning(
                        "oversized audio frame (%d bytes > %d) — dropped",
                        len(frame),
                        MAX_AUDIO_FRAME_BYTES,
                    )
                    continue
                if session is not None:
                    await session.feed_audio(frame)
                else:
                    log.debug(
                        "audio frame received before session.start (%d bytes) — dropped",
                        len(frame),
                    )
            else:
                log.warning("unknown websocket message shape: %r", msg)
    except WebSocketDisconnect:
        log.info("client disconnected")
    finally:
        if session is not None:
            await session.stop()


async def _handle_text(
    ws: WebSocket,
    raw: str,
    session: Session | None,
    stt_provider: Optional[STTProvider],
    llm_provider: Optional[LLMProvider],
) -> Session | None:
    try:
        event = client_event_adapter.validate_json(raw)
    except ValidationError as e:
        detail = e.errors()[0].get("msg", "invalid event") if e.errors() else "invalid event"
        await _send(ws, ErrorEvent(code="invalid_event", message=detail))
        return session

    if isinstance(event, SessionStart):
        if session is not None:
            return session
        if stt_provider is None:
            await _send(
                ws,
                ErrorEvent(
                    code="stt_not_configured",
                    message="Deepgram API key is not set on the server.",
                ),
            )
            await _send(ws, StatusEvent(state="error"))
            return None

        # Warn about missing LLM BEFORE starting the STT session so the event
        # ordering is deterministic (warning first, then listening, then any
        # transcripts). Posting it after start() races with the first
        # transcript event from the provider.
        if llm_provider is None:
            await _send(
                ws,
                ErrorEvent(
                    code="llm_not_configured",
                    message=(
                        "Gemini API key is not set — transcript and question "
                        "detection will work, but answers will not be streamed."
                    ),
                ),
            )

        new_session = Session(ws, stt_provider, llm_provider)
        ok = await new_session.start(
            resume=event.resume,
            job_description=event.job_description,
            mode=event.mode,
        )
        if not ok:
            await _send(ws, StatusEvent(state="error"))
            return None

        return new_session

    if isinstance(event, SessionStop):
        if session is not None:
            await session.stop()
        try:
            await ws.close()
        except Exception:
            log.debug("ws.close() after session.stop raced with client close", exc_info=True)
        return None

    if isinstance(event, QuestionManual):
        if session is None:
            await _send(
                ws,
                ErrorEvent(
                    code="not_started",
                    message="Start a session before submitting a manual question.",
                ),
            )
            return None
        await session.ask_manual(event.text)
        return session

    return session


async def _send(ws: WebSocket, event) -> None:
    await ws.send_text(event.model_dump_json())
