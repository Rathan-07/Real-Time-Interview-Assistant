import asyncio

import pytest

from app.services.stt_service import FakeSTTProvider, TranscriptEvent


@pytest.mark.asyncio
async def test_fake_stt_emits_scripted_events_in_order():
    script = [
        (0.0, TranscriptEvent(text="Hello", is_final=False)),
        (0.0, TranscriptEvent(text="Hello world", is_final=False)),
        (0.0, TranscriptEvent(text="Hello world.", is_final=True, speech_final=True)),
    ]
    seen: list[TranscriptEvent] = []

    async def collect(evt: TranscriptEvent) -> None:
        seen.append(evt)

    provider = FakeSTTProvider(script)
    async with provider.open(collect) as conn:
        await conn.send_audio(b"\x00" * 16)  # audio is discarded by the fake
        await asyncio.sleep(0.05)

    assert [e.text for e in seen] == ["Hello", "Hello world", "Hello world."]
    assert [e.is_final for e in seen] == [False, False, True]
    assert seen[-1].speech_final is True


@pytest.mark.asyncio
async def test_fake_stt_cancels_pending_events_on_exit():
    script = [
        (0.0, TranscriptEvent(text="first", is_final=False)),
        (10.0, TranscriptEvent(text="never arrives", is_final=True)),
    ]
    seen: list[TranscriptEvent] = []

    async def collect(evt: TranscriptEvent) -> None:
        seen.append(evt)

    provider = FakeSTTProvider(script)
    async with provider.open(collect):
        await asyncio.sleep(0.05)  # let the first event fire

    assert [e.text for e in seen] == ["first"]  # second was cancelled


@pytest.mark.asyncio
async def test_fake_stt_connection_methods_do_not_raise():
    provider = FakeSTTProvider([])
    async with provider.open(lambda e: asyncio.sleep(0)) as conn:
        await conn.send_audio(b"ignored")
        await conn.aclose()  # should be safe to call explicitly even inside with-block
