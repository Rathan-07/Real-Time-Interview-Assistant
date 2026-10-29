from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.deps import get_stt_provider
from app.models.events import (
    ErrorEvent,
    SessionStart,
    SessionStop,
    StatusEvent,
    client_event_adapter,
)
from app.services.session_manager import Session
from app.services.stt_service import STTProvider

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    stt_provider: Optional[STTProvider] = Depends(get_stt_provider),
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
                session = await _handle_text(ws, msg["text"], session, stt_provider)
                # After a session.stop handler closes the socket, bail out.
                if session is None and ws.client_state.name == "DISCONNECTED":
                    break
            elif msg.get("bytes") is not None:
                if session is not None:
                    await session.feed_audio(msg["bytes"])
                else:
                    log.debug(
                        "audio frame received before session.start (%d bytes) — dropped",
                        len(msg["bytes"]),
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
) -> Session | None:
    try:
        event = client_event_adapter.validate_json(raw)
    except ValidationError as e:
        detail = e.errors()[0].get("msg", "invalid event") if e.errors() else "invalid event"
        await _send(ws, ErrorEvent(code="invalid_event", message=detail))
        return session

    if isinstance(event, SessionStart):
        if session is not None:
            # Idempotent-ish: don't start twice.
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

        new_session = Session(ws, stt_provider)
        ok = await new_session.start()
        if not ok:
            await _send(ws, StatusEvent(state="error"))
            return None
        return new_session

    if isinstance(event, SessionStop):
        if session is not None:
            await session.stop()
        await ws.close()
        return None

    return session


async def _send(ws: WebSocket, event) -> None:
    await ws.send_text(event.model_dump_json())
