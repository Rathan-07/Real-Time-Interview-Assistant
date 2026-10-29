import { useCallback, useEffect, useRef, useState } from "react";

import { AnswerPanel, type AnswerMetrics } from "./components/AnswerPanel";
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

// Pre-filled demo inputs so the recording run is one click away. User can
// clear these any time; they live only in the browser's local state.
const SAMPLE_RESUME =
  "Software developer with 2+ years of experience in Python, FastAPI, " +
  "AsyncIO, and React/TypeScript. Built a RAG-based job portal, an AI " +
  "agent orchestrator, and real-time streaming prototypes. Comfortable " +
  "with WebSockets, PostgreSQL, Docker, and Claude / Gemini APIs.";
const SAMPLE_JD =
  "Software Developer – AI & Real-Time Systems. Build streaming, LLM-" +
  "backed features. Must know Python, FastAPI, async I/O, WebSockets, " +
  "React, and prompt engineering. Bonus: streaming STT, RAG, latency " +
  "instrumentation.";

export default function App() {
  const [wsStatus, setWsStatus] = useState<WsStatus>("disconnected");
  const [sessionState, setSessionState] = useState<ConnectionState>("idle");
  const [resume, setResume] = useState(SAMPLE_RESUME);
  const [jd, setJd] = useState(SAMPLE_JD);
  const [mode, setMode] = useState<AnswerMode>("concise");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [finals, setFinals] = useState<string[]>([]);
  const [interim, setInterim] = useState("");
  const [questionId, setQuestionId] = useState<string | null>(null);
  const [questionText, setQuestionText] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [answerStreaming, setAnswerStreaming] = useState(false);
  const [answerMetrics, setAnswerMetrics] = useState<AnswerMetrics | null>(null);
  const [manualText, setManualText] = useState("");

  const socketRef = useRef<AssistantSocket | null>(null);
  // Mirror of `questionId` kept in a ref so chunk/complete handlers can read
  // the active id synchronously. We used to read it inside a setState updater
  // callback, but React StrictMode double-invokes those in dev, which caused
  // answer chunks to be appended twice.
  const activeQuestionIdRef = useRef<string | null>(null);

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
      activeQuestionIdRef.current = evt.id;
      setQuestionId(evt.id);
      setQuestionText(evt.text);
      // Reset answer state — the previous answer (if any) is now stale.
      setAnswerText("");
      setAnswerStreaming(true);
      setAnswerMetrics(null);
    } else if (evt.type === "answer.chunk") {
      // Only accept chunks that belong to the currently-active question.
      // Reading from a ref (not state) is important here: StrictMode would
      // double-invoke a setState updater callback and duplicate the chunk.
      if (activeQuestionIdRef.current === evt.id) {
        setAnswerText((prev) => prev + evt.text);
      }
    } else if (evt.type === "answer.complete") {
      if (activeQuestionIdRef.current === evt.id) {
        setAnswerStreaming(false);
      }
    } else if (evt.type === "metrics") {
      if (activeQuestionIdRef.current === evt.id) {
        setAnswerMetrics({
          firstTokenMs: evt.question_to_first_chunk_ms,
          totalMs: evt.total_ms,
          chunkCount: evt.chunk_count,
          charCount: evt.char_count,
        });
      }
    }
  }, []);

  const start = useCallback(() => {
    socketRef.current?.close();
    setErrorMsg(null);
    setFinals([]);
    setInterim("");
    setQuestionId(null);
    setQuestionText(null);
    setAnswerText("");
    setAnswerStreaming(false);
    setAnswerMetrics(null);
    activeQuestionIdRef.current = null;

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

  const askManual = useCallback(() => {
    const text = manualText.trim();
    if (!text) return;
    const sock = socketRef.current;
    if (!sock || wsStatus !== "open") {
      setErrorMsg("Click Start Listening before submitting a typed question.");
      return;
    }
    sock.send({ type: "question.manual", text });
    setManualText("");
  }, [manualText, wsStatus]);

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

  // Surface mic errors into the top-level banner. The banner has multiple
  // sources (WS errors, LLM errors, mic errors), so we copy from the hook
  // into local state so the user can dismiss it. Intentional external-state
  // sync — exactly the case React effects are meant for.
  useEffect(() => {
    // oxlint-disable-next-line set-state-in-effect
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

      <section className="manual-ask">
        <input
          type="text"
          value={manualText}
          onChange={(e) => setManualText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") askManual();
          }}
          placeholder='Type a question (bypasses mic — e.g. "Explain Python generators")'
          disabled={!connected}
        />
        <button
          type="button"
          onClick={askManual}
          disabled={!connected || !manualText.trim()}
        >
          Ask
        </button>
      </section>

      {errorMsg && (
        <div className="error-banner" role="alert">
          <span>{errorMsg}</span>
          <button
            type="button"
            className="error-dismiss"
            aria-label="Dismiss"
            onClick={() => setErrorMsg(null)}
          >
            ×
          </button>
        </div>
      )}

      <TranscriptPanel finals={finals} interim={interim} />

      <DetectedQuestionPanel id={questionId} text={questionText} />

      <AnswerPanel
        questionId={questionId}
        text={answerText}
        streaming={answerStreaming}
        metrics={answerMetrics}
      />
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
