"""Dependency-injection factories for FastAPI endpoints.

Tests swap these out via `app.dependency_overrides` to avoid real provider
calls. See backend/tests/test_websocket.py.
"""
from __future__ import annotations

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.services.stt_service import DeepgramLiveProvider, STTProvider


def get_stt_provider(
    settings: Settings = Depends(get_settings),
) -> STTProvider | None:
    """Return a configured STT provider, or None if no API key is set.

    Returning None (not raising) lets the WebSocket endpoint send a typed
    error event rather than aborting the connection with a 500.
    """
    if not settings.deepgram_api_key:
        return None
    return DeepgramLiveProvider(
        api_key=settings.deepgram_api_key,
        model=settings.deepgram_model,
        interim_silence_ms=settings.question_silence_ms,
    )
