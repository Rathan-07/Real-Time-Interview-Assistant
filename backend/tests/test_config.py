import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_do_not_require_env_vars(monkeypatch):
    # Force the test to assert code defaults, not whatever is in the
    # developer's local backend/.env — otherwise a failing assertion dumps
    # the entire Settings object (including real API keys) into pytest output.
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPGRAM_MODEL", raising=False)
    monkeypatch.delenv("DEEPGRAM_LANGUAGE", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("QUESTION_SILENCE_MS", raising=False)
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    s = Settings(_env_file=None)
    assert s.deepgram_model == "nova-3"
    assert s.deepgram_language == "en"
    assert s.gemini_model == "gemini-3.6-flash"
    assert s.question_silence_ms == 1200
    assert s.frontend_origin == "http://localhost:5173"


def test_question_silence_lower_bound():
    with pytest.raises(ValidationError):
        Settings(question_silence_ms=-1)


def test_question_silence_upper_bound():
    with pytest.raises(ValidationError):
        Settings(question_silence_ms=10_001)


def test_api_keys_default_to_empty_strings(monkeypatch):
    # Bypass the developer's local backend/.env so the test asserts code defaults,
    # not the user's dev environment. (Avoids leaking real keys in test output.)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.deepgram_api_key == ""
    assert s.gemini_api_key == ""
