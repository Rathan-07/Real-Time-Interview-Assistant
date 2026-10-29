from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

# ---------- Client -> Server ----------


class SessionStart(BaseModel):
    type: Literal["session.start"] = "session.start"
    resume: str = Field(default="", max_length=20_000)
    job_description: str = Field(default="", max_length=20_000)
    mode: Literal["concise", "star"] = "concise"


class SessionStop(BaseModel):
    type: Literal["session.stop"] = "session.stop"


class QuestionManual(BaseModel):
    """Explicit question bypassing STT. Lets the UI feed a typed question
    directly to the LLM path. Useful for demos when STT is unreliable."""

    type: Literal["question.manual"] = "question.manual"
    text: str = Field(min_length=1, max_length=2_000)


ClientEvent = Annotated[
    Union[SessionStart, SessionStop, QuestionManual],
    Field(discriminator="type"),
]
client_event_adapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)


# ---------- Server -> Client ----------

ConnectionState = Literal[
    "idle", "connecting", "listening", "thinking", "answering", "stopped", "error"
]


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    state: ConnectionState
    message: str | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class TranscriptInterim(BaseModel):
    type: Literal["transcript.interim"] = "transcript.interim"
    text: str


class TranscriptFinal(BaseModel):
    type: Literal["transcript.final"] = "transcript.final"
    text: str
    speech_final: bool = False


class QuestionDetected(BaseModel):
    type: Literal["question.detected"] = "question.detected"
    id: str
    text: str


class AnswerChunk(BaseModel):
    type: Literal["answer.chunk"] = "answer.chunk"
    id: str  # same as the question.detected id this answer belongs to
    text: str


class AnswerComplete(BaseModel):
    type: Literal["answer.complete"] = "answer.complete"
    id: str


class AnswerMetrics(BaseModel):
    """Latency numbers measured server-side with a monotonic clock.

    Emitted once per completed answer. Fields are in milliseconds.
    - `question_to_first_chunk_ms`: time from question.detected to first
      answer.chunk — the headline "time to first token" number.
    - `first_chunk_to_complete_ms`: streaming duration after first token.
    - `total_ms`: convenience sum.
    """

    type: Literal["metrics"] = "metrics"
    id: str
    question_to_first_chunk_ms: int
    first_chunk_to_complete_ms: int
    total_ms: int
    chunk_count: int
    char_count: int


ServerEvent = Union[
    StatusEvent,
    ErrorEvent,
    TranscriptInterim,
    TranscriptFinal,
    QuestionDetected,
    AnswerChunk,
    AnswerComplete,
    AnswerMetrics,
]
