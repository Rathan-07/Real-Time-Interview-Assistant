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


ClientEvent = Annotated[Union[SessionStart, SessionStop], Field(discriminator="type")]
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


ServerEvent = Union[StatusEvent, ErrorEvent]
