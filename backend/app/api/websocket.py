import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.models.events import (
    ErrorEvent,
    SessionStart,
    SessionStop,
    StatusEvent,
    client_event_adapter,
)

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    await _send(ws, StatusEvent(state="idle", message="connected"))

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text") is not None:
                await _handle_text(ws, msg["text"])
            elif msg.get("bytes") is not None:
                # Phase 2: binary audio frames get forwarded to Deepgram.
                # Phase 1 drops them silently so the socket stays usable.
                log.debug("audio frame received (%d bytes) — ignored until Phase 2", len(msg["bytes"]))
            else:
                log.warning("unknown websocket message shape: %r", msg)
    except WebSocketDisconnect:
        log.info("client disconnected")
    finally:
        # Phase 2+ will cancel audio-forwarding tasks and close provider connections here.
        pass


async def _handle_text(ws: WebSocket, raw: str) -> None:
    try:
        event = client_event_adapter.validate_json(raw)
    except ValidationError as e:
        detail = e.errors()[0].get("msg", "invalid event") if e.errors() else "invalid event"
        await _send(ws, ErrorEvent(code="invalid_event", message=detail))
        return

    if isinstance(event, SessionStart):
        await _send(ws, StatusEvent(state="listening", message=f"mode={event.mode}"))
    elif isinstance(event, SessionStop):
        await _send(ws, StatusEvent(state="stopped"))
        await ws.close()


async def _send(ws: WebSocket, event: StatusEvent | ErrorEvent) -> None:
    await ws.send_text(event.model_dump_json())
