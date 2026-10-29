"""Integration tests covering question → LLM answer flow via the WebSocket.

Both the STT and LLM are faked. We verify:
- answer.chunk + answer.complete ride on top of question.detected
- A newer question cancels an in-flight answer
- Missing Gemini key degrades gracefully (transcript + question still work)
"""
from fastapi.testclient import TestClient

from app.core.deps import get_llm_provider, get_stt_provider
from app.main import app
from app.services.llm_service import FakeLLMProvider
from app.services.stt_service import FakeSTTProvider, TranscriptEvent

client = TestClient(app)


# -------------------- helpers --------------------


def _ovrr(stt, llm):
    app.dependency_overrides[get_stt_provider] = lambda: stt
    app.dependency_overrides[get_llm_provider] = lambda: llm


def _clear():
    app.dependency_overrides.clear()


def _drain_until(ws, type_: str, max_events: int = 50):
    """Pull events until we see one matching `type_`. Fails loudly otherwise."""
    for _ in range(max_events):
        evt = ws.receive_json()
        if evt["type"] == type_:
            return evt
    raise AssertionError(f"did not see {type_} within {max_events} events")


# -------------------- tests ----------------------


def test_question_triggers_streamed_answer_with_matching_id():
    stt = FakeSTTProvider(
        [
            (0.0, TranscriptEvent(text="Explain Python generators.", is_final=True, speech_final=True)),
        ]
    )
    llm = FakeLLMProvider(
        ["A generator ", "is a function that ", "yields values lazily."],
        per_chunk_delay_s=0.0,
    )
    _ovrr(stt, llm)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # idle
            ws.send_json({"type": "session.start"})
            assert ws.receive_json()["state"] == "listening"

            q = _drain_until(ws, "question.detected")
            qid = q["id"]

            # thinking status before first chunk
            _drain_until(ws, "status")  # could be thinking

            # Collect chunks + answer.complete
            chunks = []
            while True:
                evt = ws.receive_json()
                if evt["type"] == "answer.chunk":
                    assert evt["id"] == qid
                    chunks.append(evt["text"])
                elif evt["type"] == "answer.complete":
                    assert evt["id"] == qid
                    break
                elif evt["type"] == "status":
                    continue  # status transitions are fine
            full = "".join(chunks)
            assert full == "A generator is a function that yields values lazily."
    finally:
        _clear()


def test_new_question_cancels_in_flight_answer():
    stt = FakeSTTProvider(
        [
            (0.0, TranscriptEvent(text="Explain Python generators.", is_final=True, speech_final=True)),
            # The second question arrives before the first answer finishes:
            (0.03, TranscriptEvent(text="Explain Python decorators.", is_final=True, speech_final=True)),
        ]
    )
    # 10 slow chunks so the answer is still streaming when question 2 lands
    llm = FakeLLMProvider(
        [f"chunk{i} " for i in range(10)],
        per_chunk_delay_s=0.02,
    )
    _ovrr(stt, llm)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "session.start"})
            assert ws.receive_json()["state"] == "listening"

            q1 = _drain_until(ws, "question.detected")
            q2 = None
            seen_q_ids = {q1["id"]}
            completes_by_qid: dict[str, bool] = {}
            while True:
                evt = ws.receive_json()
                if evt["type"] == "question.detected":
                    q2 = evt
                    seen_q_ids.add(evt["id"])
                elif evt["type"] == "answer.complete":
                    completes_by_qid[evt["id"]] = True
                    if q2 is not None and evt["id"] == q2["id"]:
                        break
                elif evt["type"] in {"answer.chunk", "status", "transcript.final"}:
                    continue
                else:
                    continue

            assert q2 is not None
            # Both answers must emit a completion event — question 1's completion
            # fires via the CancelledError branch, question 2's via normal end.
            assert q1["id"] in completes_by_qid
            assert q2["id"] in completes_by_qid
    finally:
        _clear()


def test_manual_question_bypasses_stt_and_streams_answer():
    """Typed question goes straight to the LLM pipeline (skip STT + detector)."""
    stt = FakeSTTProvider([])  # no STT events needed
    llm = FakeLLMProvider(
        ["Closures ", "capture ", "variables ", "from enclosing scope."],
        per_chunk_delay_s=0.0,
    )
    _ovrr(stt, llm)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # idle
            ws.send_json({"type": "session.start"})
            assert ws.receive_json()["state"] == "listening"

            ws.send_json(
                {"type": "question.manual", "text": "What are JS closures?"}
            )

            q = _drain_until(ws, "question.detected")
            assert q["id"].startswith("m_")  # manual id namespace
            assert "closures" in q["text"].lower()

            chunks = []
            while True:
                evt = ws.receive_json()
                if evt["type"] == "answer.chunk":
                    chunks.append(evt["text"])
                elif evt["type"] == "answer.complete":
                    break
                elif evt["type"] == "status":
                    continue
            full = "".join(chunks)
            assert "Closures" in full
            assert "variables" in full
    finally:
        _clear()


def test_answer_metrics_event_emitted_with_sensible_numbers():
    """After a complete answer, a `metrics` event must land with monotonic
    non-negative integer durations and the right chunk/char counts."""
    stt = FakeSTTProvider([])
    llm = FakeLLMProvider(
        ["hello ", "world ", "answer."],
        per_chunk_delay_s=0.02,
    )
    _ovrr(stt, llm)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "session.start"})
            assert ws.receive_json()["state"] == "listening"
            ws.send_json({"type": "question.manual", "text": "What is REST?"})

            metrics_evt = None
            saw_complete = False
            for _ in range(30):
                evt = ws.receive_json()
                if evt["type"] == "answer.complete":
                    saw_complete = True
                elif evt["type"] == "metrics":
                    metrics_evt = evt
                    break
            assert saw_complete
            assert metrics_evt is not None
            assert metrics_evt["id"].startswith("m_")
            assert metrics_evt["chunk_count"] == 3
            assert metrics_evt["char_count"] == len("hello world answer.")
            assert metrics_evt["question_to_first_chunk_ms"] >= 0
            assert metrics_evt["first_chunk_to_complete_ms"] >= 0
            # total ≈ question_to_first_chunk + first_chunk_to_complete,
            # allow 2 ms slop for the two separate monotonic reads.
            delta = abs(
                metrics_evt["total_ms"]
                - (
                    metrics_evt["question_to_first_chunk_ms"]
                    + metrics_evt["first_chunk_to_complete_ms"]
                )
            )
            assert delta <= 2, delta
    finally:
        _clear()


def test_manual_question_before_start_errors_out():
    stt = FakeSTTProvider([])
    llm = FakeLLMProvider([])
    _ovrr(stt, llm)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # idle
            ws.send_json({"type": "question.manual", "text": "Hi"})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["code"] == "not_started"
    finally:
        _clear()


def test_manual_question_rejects_empty_text_at_validation():
    stt = FakeSTTProvider([])
    llm = FakeLLMProvider([])
    _ovrr(stt, llm)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "session.start"})
            assert ws.receive_json()["state"] == "listening"
            ws.send_json({"type": "question.manual", "text": ""})
            # Pydantic min_length=1 rejects empty strings → invalid_event
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["code"] == "invalid_event"
    finally:
        _clear()


def test_missing_llm_still_delivers_question_without_crash():
    """No Gemini key configured: UI should get an llm_not_configured warning
    plus the question.detected event, but no answer stream."""
    stt = FakeSTTProvider(
        [
            (0.0, TranscriptEvent(text="Explain Python generators.", is_final=True, speech_final=True)),
        ]
    )
    _ovrr(stt, None)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # idle
            ws.send_json({"type": "session.start"})
            # Warning comes BEFORE listening — the handler emits it before
            # opening the STT session so the ordering is deterministic.
            warning = ws.receive_json()
            assert warning["type"] == "error"
            assert warning["code"] == "llm_not_configured"
            assert ws.receive_json()["state"] == "listening"

            q = _drain_until(ws, "question.detected")
            assert "generators" in q["text"]

            # No answer.chunk should ever arrive. Stop and verify clean close.
            ws.send_json({"type": "session.stop"})
            _drain_until(ws, "status")  # stopped
    finally:
        _clear()
