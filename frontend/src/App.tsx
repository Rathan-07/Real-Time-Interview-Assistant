import { useCallback, useEffect, useRef, useState } from "react";

import { DetectedQuestionPanel } from "./components/DetectedQuestionPanel";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useAudioStream } from "./hooks/useAudioStream";
import { AssistantSocket, type WsStatus } from "./services/websocket";
import type {
  AnswerMode,
  ConnectionState,
  ServerEvent,
} from "./types/events";
import "./App.css";

const WS_URL =
  (import.meta.env.VITE_WS_URL as string | undefined) ??
  "ws://localhost:8000/ws";

export default function App() {
  const [wsStatus, setWsStatus] = useState<WsStatus>("disconnected");
  const [sessionState, setSessionState] = useState<ConnectionState>("idle");
  const [resume, setResume] = useState("");
  const [jd, setJd] = useState("");
  const [mode, setMode] = useState<AnswerMode>("concise");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [finals, setFinals] = useState<string[]>([]);
  const [interim, setInterim] = useState("");
  const [questionId, setQuestionId] = useState<string | null>(null);
  const [questionText, setQuestionText] = useState<string | null>(null);

  const socketRef = useRef<AssistantSocket | null>(null);

  const sendBinary = useCallback((blob: Blob) => {
    socketRef.current?.sendBinary(blob);
  }, []);

  const {
    recording: micRecording,
    permission: micPermission,
    error: micError,
    start: startMic,
    stop: stopMic,
  } = useAudioStream({ onChunk: sendBinary });

  const handleEvent = useCallback((evt: ServerEvent) => {
    if (evt.type === "status") {
      setSessionState(evt.state);
      if (evt.state !== "error") setErrorMsg(null);
    } else if (evt.type === "error") {
      setErrorMsg(`${evt.code}: ${evt.message}`);
      setSessionState("error");
    } else if (evt.type === "transcript.interim") {
      setInterim(evt.text);
    } else if (evt.type === "transcript.final") {
      setFinals((prev) => [...prev, evt.text]);
      setInterim("");
    } else if (evt.type === "question.detected") {
      setQuestionId(evt.id);
      setQuestionText(evt.text);
    }
  }, []);

  const start = useCallback(() => {
    socketRef.current?.close();
    setErrorMsg(null);
    setFinals([]);
    setInterim("");
    setQuestionId(null);
    setQuestionText(null);

    const sock = new AssistantSocket(WS_URL, {
      onOpen: () =>
        sock.send({
          type: "session.start",
          resume,
          job_description: jd,
          mode,
        }),
      onEvent: handleEvent,
      onStatus: setWsStatus,
      onError: () =>
        setErrorMsg("WebSocket error — is the backend running on port 8000?"),
    });
    socketRef.current = sock;
    sock.connect();
  }, [handleEvent, resume, jd, mode]);

  const stop = useCallback(() => {
    stopMic();
    const sock = socketRef.current;
    if (!sock) return;
    // Send session.stop and let the server emit `status: stopped` and close
    // the socket. Our WebSocket's onclose handler will flip wsStatus → closed
    // and null out the internal ws. We DO NOT call sock.close() here — that
    // caused a race where the browser's close frame beat the server's stop
    // reply, triggering a WebSocketDisconnected in the backend.
    sock.send({ type: "session.stop" });
  }, [stopMic]);

  // Start/stop the mic in response to backend session state.
  // Server-driven: we only capture audio once Deepgram is actually ready.
  useEffect(() => {
    if (sessionState === "listening" && !micRecording) {
      void startMic();
    } else if (
      (sessionState === "stopped" ||
        sessionState === "error" ||
        sessionState === "idle") &&
      micRecording
    ) {
      stopMic();
    }
  }, [sessionState, micRecording, startMic, stopMic]);

  // Surface mic errors into the top-level banner.
  useEffect(() => {
    if (micError) setErrorMsg(micError);
  }, [micError]);

  useEffect(() => {
    return () => {
      stopMic();
      socketRef.current?.close();
    };
  }, [stopMic]);

  const connected = wsStatus === "open";

  return (
    <main className="shell">
      <header className="header">
        <h1>Real-Time Interview Assistant</h1>
        <div className="status-pills">
          <StatusPill label="WS" value={wsStatus} />
          <StatusPill label="Session" value={sessionState} />
          <StatusPill label="Mic" value={micRecording ? "recording" : micPermission} />
        </div>
      </header>

      <section className="inputs">
        <label className="field">
          <span>Resume / Summary</span>
          <textarea
            value={resume}
            onChange={(e) => setResume(e.target.value)}
            rows={6}
            placeholder="Paste a short resume or professional summary…"
          />
        </label>

        <label className="field">
          <span>Job Description</span>
          <textarea
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            rows={6}
            placeholder="Paste the role / JD the interviewer is hiring for…"
          />
        </label>

        <label className="field mode-field">
          <span>Answer mode</span>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as AnswerMode)}
          >
            <option value="concise">Concise (60–90 words)</option>
            <option value="star">STAR (behavioral)</option>
          </select>
        </label>
      </section>

      <section className="controls">
        <button
          type="button"
          onClick={start}
          disabled={connected || wsStatus === "connecting"}
        >
          Start Listening
        </button>
        <button type="button" onClick={stop} disabled={!connected}>
          Stop Listening
        </button>
      </section>

      {errorMsg && <div className="error-banner">{errorMsg}</div>}

      <TranscriptPanel finals={finals} interim={interim} />

      <DetectedQuestionPanel id={questionId} text={questionText} />

      <section className="panel">
        <h2>Answer</h2>
        <p className="placeholder">
          Streaming Gemini answer renders here in Phase 4.
        </p>
      </section>
    </main>
  );
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return (
    <span className={`pill pill-${value}`}>
      <strong>{label}:</strong> {value}
    </span>
  );
}
