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

export interface QuestionManual {
  type: "question.manual";
  text: string;
}

export type ClientEvent = SessionStart | SessionStop | QuestionManual;

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

export interface TranscriptInterimEvent {
  type: "transcript.interim";
  text: string;
}

export interface TranscriptFinalEvent {
  type: "transcript.final";
  text: string;
  speech_final: boolean;
}

export interface QuestionDetectedEvent {
  type: "question.detected";
  id: string;
  text: string;
}

export interface AnswerChunkEvent {
  type: "answer.chunk";
  id: string;
  text: string;
}

export interface AnswerCompleteEvent {
  type: "answer.complete";
  id: string;
}

export interface AnswerMetricsEvent {
  type: "metrics";
  id: string;
  question_to_first_chunk_ms: number;
  first_chunk_to_complete_ms: number;
  total_ms: number;
  chunk_count: number;
  char_count: number;
}

export type ServerEvent =
  | StatusEvent
  | ServerErrorEvent
  | TranscriptInterimEvent
  | TranscriptFinalEvent
  | QuestionDetectedEvent
  | AnswerChunkEvent
  | AnswerCompleteEvent
  | AnswerMetricsEvent;
