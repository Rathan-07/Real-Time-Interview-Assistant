import { useCallback, useEffect, useRef, useState } from "react";

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
  const socketRef = useRef<AssistantSocket | null>(null);

  const handleEvent = useCallback((evt: ServerEvent) => {
    if (evt.type === "status") {
      setSessionState(evt.state);
      if (evt.state !== "error") setErrorMsg(null);
    } else if (evt.type === "error") {
      setErrorMsg(`${evt.code}: ${evt.message}`);
      setSessionState("error");
    }
  }, []);

  const start = useCallback(() => {
    socketRef.current?.close();
    setErrorMsg(null);

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
      onError: () => setErrorMsg("WebSocket error — is the backend running?"),
    });
    socketRef.current = sock;
    sock.connect();
  }, [handleEvent, resume, jd, mode]);

  const stop = useCallback(() => {
    const sock = socketRef.current;
    if (!sock) return;
    sock.send({ type: "session.stop" });
    sock.close();
    socketRef.current = null;
  }, []);

  useEffect(() => {
    return () => socketRef.current?.close();
  }, []);

  const connected = wsStatus === "open";

  return (
    <main className="shell">
      <header className="header">
        <h1>Real-Time Interview Assistant</h1>
        <div className="status-pills">
          <StatusPill label="WS" value={wsStatus} />
          <StatusPill label="Session" value={sessionState} />
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

      <section className="panel">
        <h2>Transcript</h2>
        <p className="placeholder">Live transcript renders here in Phase 2.</p>
      </section>

      <section className="panel">
        <h2>Detected question</h2>
        <p className="placeholder">Detected questions render here in Phase 3.</p>
      </section>

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
