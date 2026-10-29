// Mirror of backend/app/models/events.py — keep both sides in sync by hand.

export type AnswerMode = "concise" | "star";

export type ConnectionState =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "answering"
  | "stopped"
  | "error";

// ---------- Client -> Server ----------

export interface SessionStart {
  type: "session.start";
  resume: string;
  job_description: string;
  mode: AnswerMode;
}

export interface SessionStop {
  type: "session.stop";
}

export type ClientEvent = SessionStart | SessionStop;

// ---------- Server -> Client ----------

export interface StatusEvent {
  type: "status";
  state: ConnectionState;
  message?: string | null;
}

export interface ServerErrorEvent {
  type: "error";
  code: string;
  message: string;
}

export type ServerEvent = StatusEvent | ServerErrorEvent;
