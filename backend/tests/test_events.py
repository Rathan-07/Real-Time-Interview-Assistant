import pytest
from pydantic import ValidationError

from app.models.events import (
    ErrorEvent,
    SessionStart,
    SessionStop,
    StatusEvent,
    client_event_adapter,
)


def test_session_start_parses_from_json():
    raw = '{"type":"session.start","resume":"R","job_description":"JD","mode":"concise"}'
    evt = client_event_adapter.validate_json(raw)
    assert isinstance(evt, SessionStart)
    assert evt.resume == "R"
    assert evt.mode == "concise"


def test_session_start_defaults_to_concise_mode():
    evt = client_event_adapter.validate_json('{"type":"session.start"}')
    assert isinstance(evt, SessionStart)
    assert evt.mode == "concise"


def test_session_stop_parses_from_json():
    evt = client_event_adapter.validate_json('{"type":"session.stop"}')
    assert isinstance(evt, SessionStop)


def test_unknown_type_rejected():
    with pytest.raises(ValidationError):
        client_event_adapter.validate_json('{"type":"session.explode"}')


def test_invalid_mode_rejected():
    with pytest.raises(ValidationError):
        client_event_adapter.validate_json(
            '{"type":"session.start","mode":"casual"}'
        )


def test_oversized_resume_rejected():
    big = "x" * 20_001
    with pytest.raises(ValidationError):
        SessionStart(resume=big)


def test_status_event_serialization_includes_type_tag():
    s = StatusEvent(state="listening")
    data = s.model_dump_json()
    assert '"type":"status"' in data
    assert '"state":"listening"' in data


def test_error_event_requires_code_and_message():
    err = ErrorEvent(code="x", message="y")
    assert err.code == "x"
    assert err.message == "y"
