from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ws_sends_initial_idle_status():
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert msg["state"] == "idle"


def test_ws_session_start_transitions_to_listening():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # drain initial idle
        ws.send_json(
            {
                "type": "session.start",
                "resume": "r",
                "job_description": "jd",
                "mode": "concise",
            }
        )
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert msg["state"] == "listening"
        assert "concise" in (msg.get("message") or "")


def test_ws_malformed_json_returns_error_event_not_crash():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text("{not valid json")
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "invalid_event"


def test_ws_unknown_event_type_returns_error():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "session.explode"})
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_ws_session_stop_closes_cleanly():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "session.stop"})
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert msg["state"] == "stopped"
        # Server should close after stop; next receive raises.
        import pytest
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_binary_frames_do_not_crash_session():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00\x01\x02\x03")
        # Follow with a text event to prove the socket is still alive.
        ws.send_json({"type": "session.start"})
        msg = ws.receive_json()
        assert msg["type"] == "status"
        assert msg["state"] == "listening"
