import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_do_not_require_env_vars():
    s = Settings()
    assert s.deepgram_model == "nova-2"
    assert s.gemini_model == "gemini-2.0-flash"
    assert s.question_silence_ms == 800
    assert s.frontend_origin == "http://localhost:5173"


def test_question_silence_lower_bound():
    with pytest.raises(ValidationError):
        Settings(question_silence_ms=-1)


def test_question_silence_upper_bound():
    with pytest.raises(ValidationError):
        Settings(question_silence_ms=10_001)


def test_api_keys_default_to_empty_strings():
    s = Settings()
    assert s.deepgram_api_key == ""
    assert s.gemini_api_key == ""
