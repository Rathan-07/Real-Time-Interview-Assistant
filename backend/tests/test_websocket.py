import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.deps import get_stt_provider
from app.main import app
from app.services.stt_service import FakeSTTProvider, TranscriptEvent

client = TestClient(app)


# ------------------- fixtures / helpers -------------------


@pytest.fixture
def with_fake_stt():
    """Override get_stt_provider so WS tests don't need Deepgram.

    Each test provides its own script via the inner factory.
    """

    def _install(script):
        app.dependency_overrides[get_stt_provider] = lambda: FakeSTTProvider(script)

    yield _install
    app.dependency_overrides.clear()


@pytest.fixture
def with_no_stt():
    """Simulate 'DEEPGRAM_API_KEY not set' by returning None from the dep."""
    app.dependency_overrides[get_stt_provider] = lambda: None
    yield
    app.dependency_overrides.clear()


# ---------------------- base plumbing ---------------------


def test_health_endpoint_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ws_sends_initial_idle_status(with_fake_stt):
    with_fake_stt([])
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert msg["state"] == "idle"


def test_ws_malformed_json_returns_error_event(with_fake_stt):
    with_fake_stt([])
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text("{not valid json")
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "invalid_event"


def test_ws_session_start_transitions_to_listening(with_fake_stt):
    with_fake_stt([])
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "session.start",
                "resume": "",
                "job_description": "",
                "mode": "concise",
            }
        )
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert msg["state"] == "listening"


def test_ws_session_stop_closes_cleanly(with_fake_stt):
    with_fake_stt([])
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "session.start"})
        assert ws.receive_json()["state"] == "listening"
        ws.send_json({"type": "session.stop"})
        assert ws.receive_json()["state"] == "stopped"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


# ---------------------- transcript flow -------------------


def test_ws_forwards_interim_and_final_transcripts(with_fake_stt):
    with_fake_stt(
        [
            (0.0, TranscriptEvent(text="hello", is_final=False)),
            (0.0, TranscriptEvent(text="hello world", is_final=False)),
            (0.0, TranscriptEvent(text="hello world.", is_final=True, speech_final=True)),
        ]
    )
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # idle
        ws.send_json({"type": "session.start"})
        assert ws.receive_json()["state"] == "listening"

        received_types = []
        received_texts = []
        for _ in range(3):
            m = ws.receive_json()
            received_types.append(m["type"])
            received_texts.append(m.get("text"))

        assert received_types == [
            "transcript.interim",
            "transcript.interim",
            "transcript.final",
        ]
        assert received_texts == ["hello", "hello world", "hello world."]


def test_ws_binary_audio_drops_before_session_start(with_fake_stt):
    """Binary frames before session.start must not crash — just get dropped."""
    with_fake_stt([])
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00" * 16)
        # Prove the socket is still alive:
        ws.send_json({"type": "session.start"})
        assert ws.receive_json()["state"] == "listening"


def test_ws_binary_audio_during_session_is_accepted(with_fake_stt):
    with_fake_stt([])
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "session.start"})
        assert ws.receive_json()["state"] == "listening"
        for _ in range(5):
            ws.send_bytes(b"\x00" * 1024)
        ws.send_json({"type": "session.stop"})
        assert ws.receive_json()["state"] == "stopped"


# --------------------- missing key path --------------------


def test_ws_reports_stt_not_configured_when_key_missing(with_no_stt):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # idle
        ws.send_json({"type": "session.start"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "stt_not_configured"
        status = ws.receive_json()
        assert status["type"] == "status"
        assert status["state"] == "error"
