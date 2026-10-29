import asyncio
import json
from typing import Any

import pytest

from app.services.session_manager import Session
from app.services.stt_service import FakeSTTProvider, TranscriptEvent


class FakeWS:
    """Minimal duck of starlette.WebSocket for Session tests.

    We only need send_text — Session never calls accept/receive/close itself.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@pytest.mark.asyncio
async def test_session_start_emits_listening_then_transcripts():
    script = [
        (0.0, TranscriptEvent(text="hi", is_final=False)),
        (0.02, TranscriptEvent(text="hi there", is_final=True, speech_final=True)),
    ]
    ws = FakeWS()
    session = Session(ws, FakeSTTProvider(script))  # type: ignore[arg-type]
    ok = await session.start()
    assert ok is True
    await asyncio.sleep(0.1)
    await session.stop()

    types = [m["type"] for m in ws.sent]
    assert types[0] == "status" and ws.sent[0]["state"] == "listening"
    assert "transcript.interim" in types
    assert "transcript.final" in types
    assert types[-1] == "status" and ws.sent[-1]["state"] == "stopped"


@pytest.mark.asyncio
async def test_session_stop_is_idempotent():
    ws = FakeWS()
    session = Session(ws, FakeSTTProvider([]))  # type: ignore[arg-type]
    await session.start()
    await session.stop()
    await session.stop()
    stopped_states = [m for m in ws.sent if m.get("type") == "status" and m.get("state") == "stopped"]
    assert len(stopped_states) == 1  # second stop is a no-op


@pytest.mark.asyncio
async def test_session_emits_error_when_provider_fails_to_open():
    class ExplodingProvider:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def open(self, _on_transcript):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")
            yield  # pragma: no cover

    ws = FakeWS()
    session = Session(ws, ExplodingProvider())  # type: ignore[arg-type]
    ok = await session.start()
    assert ok is False

    error_events = [m for m in ws.sent if m.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["code"] == "stt_failed"
