# Real-Time Interview Assistant

A proof-of-concept that listens to an interviewer's question in real time and
streams back a concise, grounded suggested answer. Built against the
"Software Engineer – AI & Real-Time Systems" assessment brief.

**Core loop:**

```
Browser mic ─WebSocket binary─▶ FastAPI /ws ─▶ Deepgram live STT
                                     │                  │
                                     │  interim+final ◀─┘
                                     ▼
                              QuestionDetector (rules)
                                     │
                                     ▼ (if real question)
                              Gemini streaming ─▶ WebSocket JSON ─▶ React UI
```

One browser WebSocket per session carries both the audio frames (binary) and
every typed JSON event (status, transcript, detected question, answer chunks,
latency metrics, errors).

---

## Repository layout

```
backend/
  app/
    api/websocket.py            FastAPI /ws endpoint
    core/
      config.py                 Pydantic-settings loader
      deps.py                   DI factories for STT + LLM providers
    models/events.py            Typed client/server event schemas
    services/
      stt_service.py            Deepgram adapter + FakeSTT (Protocol-based)
      llm_service.py            Gemini adapter + FakeLLM (Protocol-based)
      prompt_builder.py         Pure prompt construction (concise / STAR)
      question_detector.py      Deterministic question classifier
      session_manager.py        Per-WebSocket interview session
    main.py                     App bootstrap + CORS + health check
  tests/                        72 pytest tests, no external keys needed
  scripts/check_providers.py    Live diagnostic for both providers
  requirements.txt / requirements-dev.txt
  .env.example                  Placeholders, no secrets

frontend/
  src/
    App.tsx                     Dashboard shell
    components/                 TranscriptPanel, DetectedQuestionPanel, AnswerPanel
    hooks/useAudioStream.ts     MediaRecorder → Opus
    services/websocket.ts       AssistantSocket wrapper
    types/events.ts             Mirror of backend event schemas
```

---

## Setup from a clean machine

### Prerequisites
- macOS or Linux
- Python 3.12 (3.11 also works)
- Node 20+ (tested on 24)
- A Deepgram API key (free $200 trial credit)
- A Google Gemini API key (free tier via Google AI Studio)

### Backend

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env and fill in DEEPGRAM_API_KEY + GEMINI_API_KEY. Do not commit .env.
```

Smoke-test the keys:

```bash
.venv/bin/python scripts/check_providers.py
# Should print:
# [OK  ] deepgram  — key valid, 1 project(s)
# [OK  ] gemini    — model 'gemini-3.6-flash' responded (N chars)
```

Run the backend:

```bash
.venv/bin/python -m uvicorn app.main:app --reload
# listening on http://127.0.0.1:8000
```

Run the test suite (no external calls — all tests use the Fake providers):

```bash
.venv/bin/python -m pytest -v
# 72 passed in ~0.7s
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Open the printed Vite URL (default http://localhost:5173)
```

Click **Start Listening**, allow the mic prompt, then either speak a question
or type one into the input below the Start/Stop buttons.

---

## Architecture and data flow

**One WebSocket per session.** The browser connects to `/ws`; the backend
accepts, sends an initial `status: idle`, then waits for the client to send
a `session.start` event with the resume, job description, and answer mode.

**STT adapter.** On `session.start`, the backend opens a Deepgram live
WebSocket (owned by `Session._run`). Audio frames the client sends over its
WS get forwarded to Deepgram with `send_media`. Deepgram's result messages
and `UtteranceEnd` events are mapped to a provider-neutral `TranscriptEvent`
dataclass. The adapter sits behind the `STTProvider` `Protocol`; tests
replace it with `FakeSTTProvider` via FastAPI dependency overrides.

**Question detection.** Every finalized transcript segment is fed to
`QuestionDetector.observe`. Interim results are ignored. Finalized segments
are buffered until Deepgram emits `speech_final=True`, an `UtteranceEnd`,
or the buffer accumulates terminal punctuation and ≥ 2 words (a fallback
needed because Deepgram occasionally never emits `speech_final`). The
detector then applies ordered rules: filler blacklist → small-talk prefix
blocklist → length check → terminal-"?" accept → WH-word accept → interview-
phrase prefix accept. A deque of normalized hashes dedupes repeated
utterances across a 3-item window.

**LLM streaming.** When the detector fires, Session cancels any in-flight
answer task and spawns a new one. `prompt_builder.build_prompt` constructs
a system message (interview voice, concise/STAR structure, explicit
anti-hallucination guard) and a user message (resume + JD + question).
`GeminiStreamingProvider.stream` opens a streaming request with
`asyncio.wait_for` around both the connect and each chunk read, with one
retry on transient 5xx. Chunks are forwarded to the client as
`answer.chunk` events; after `answer.complete`, a `metrics` event carries
server-measured latency (monotonic clock).

**Lifecycle guarantees.** `Session.stop()` is idempotent, bounded (3 s then
cancel), cancels any in-flight answer, resets the detector, and closes the
Deepgram connection cleanly. Browser disconnects are caught in the
WebSocket handler's `WebSocketDisconnect` branch and route through the
same cleanup.

**Typed-input bypass.** A `question.manual` event lets the UI feed a typed
question directly to the LLM path, skipping STT. Useful when STT quality is
unreliable in a noisy room — see "Known limitations" below.

---

## Key decisions and trade-offs

**Deepgram over AssemblyAI / Google STT.** Deepgram's live WebSocket client
in `deepgram-sdk` v7 handles interim results, endpointing, and `UtteranceEnd`
with one Python call. Model switching (`nova-2` → `nova-3`) is one env var.
`nova-3` with `language=en` gives notably better accent handling than the
`nova-2` default. Downside: proprietary SDK, less flexible than raw WS.

**Google Gemini over OpenAI / Anthropic.** Gemini's free tier is generous
enough for the demo and the official `google-genai` async client supports
streaming out of the box. Model choice (`gemini-3.6-flash` default, `3.5-flash`,
`3.1-flash-lite` as faster alternates) is one env var — demonstrated by
switching mid-session during development when 3.6 started 503-ing.

**Deterministic question detection, not an LLM classifier.** The brief
accepts either; we chose rules because an LLM classifier on every pause
would add ~300 ms + token cost without buying measurable accuracy over
curated heuristics. The rules handle noisy transcripts explicitly: short
filler is rejected, small-talk prefixes block "how are you doing", and the
2-word threshold accepts "Explain CORS" while still filtering acknowledgments.

**Protocol-based adapters.** `STTProvider` and `LLMProvider` are Python
`Protocol`s with 1–2 methods each. The real adapter and its fake sibling
both implement the same shape. Tests inject `FakeSTTProvider` /
`FakeLLMProvider` via FastAPI `app.dependency_overrides` — zero mocking
magic. Swapping Deepgram for AssemblyAI is one new adapter file; nothing
downstream changes.

**MediaRecorder → WebM/Opus, not AudioWorklet → PCM.** MediaRecorder with
`timeslice=250 ms` chunks is ~40 lines of frontend code and works in
Chrome/Edge/Firefox. Deepgram sniffs the WebM container header, so we
don't pass `encoding` or `sample_rate`. The AudioWorklet path would give
slightly lower first-chunk latency but needs a worklet file, downsampling
from 48 kHz, and manual packet framing — unjustified for a POC.

**No LangChain.** One streaming call per question. No chains, tools,
retrievers, or memory in scope. Adding LangChain would wrap the direct
`google-genai` call in extra layers, hurt first-token latency, and dilute
the "I can explain every line" story. The `LLMProvider` protocol gives
provider swappability without any of that.

**Nice-to-haves chosen (brief says pick at most 2):** different answer
modes (concise + STAR) and latency metrics shown in the UI. Conversation
memory was deliberately skipped — the brief rewards a solid core over
feature count.

**No auto-reconnect on WebSocket.** A reconnect loop would silently resume
sending audio after a transient outage, which is worse than making the
user press Start again — the rebrief says "stop should release all
resources predictably." Added to "next week" instead.

---

## Known limitations

- **STT accuracy varies by voice and mic.** Deepgram occasionally mishears
  short imperative words (e.g. "Explain" → "Expense") on non-American
  accents and laptop mics. We mitigate with (a) `nova-3` + `language=en`,
  (b) a typed-input bypass that goes straight to the LLM path.
- **Free-tier Gemini models rotate throttling.** During development
  individual flash models hit transient 503s and >15 s first-chunk delays.
  Model is env-var swappable; the adapter has one 5xx retry and 20 s chunk
  timeouts so a transient blip surfaces as a dismissible error rather than
  a UI hang.
- **Mic only — no tab/system audio.** The brief allows either; mic was
  simpler to validate. For an actual Google Meet / Zoom use case,
  `getDisplayMedia` with audio capture is the right path.
- **One concurrent session per backend process.** No multi-user or
  horizontal scaling; the brief says databases and deployment are out of
  scope. A production version would need a session registry and would
  want to pool Deepgram connections.
- **Prompt-based anti-hallucination is not a guarantee.** The system
  prompt explicitly forbids fabrication, but any LLM can still invent
  under pressure. For critical use a secondary verifier call would be
  needed.
- **Browser support.** Tested in Chrome and Firefox on macOS. Safari's
  MediaRecorder emits MP4/AAC which Deepgram handles less reliably; the
  code does not currently detect-and-fallback.
- **Latency target.** Brief asks for <3 s question-to-first-token. On
  `gemini-3.1-flash-lite` or `gemini-3.5-flash` with the free tier
  behaving, measured ~1.5–2.5 s locally. Under Google throttling it can
  spike to 4–8 s and we surface this honestly via the latency badge
  rather than hiding it.

---

## Testing

**Backend: 72 pytest tests, no external keys required.**

```bash
cd backend && .venv/bin/python -m pytest -v
```

Coverage areas:
- Config validation (bounds, env-file isolation to prevent key leakage in test output)
- Event schema round-trips (discriminated unions, max-length rejection, unknown types)
- Question detector (21 tests: WH / prefix / "?" / filler / small-talk / dedup / buffering / split-chunk rejoin / punctuation flush / buffer cap)
- Prompt builder (8 tests: context inclusion, STAR structure, anti-hallucination guards, purity)
- STT fake (3 tests: scripted events, cancellation, aclose safety)
- Session manager (3 tests: lifecycle, idempotent stop, provider failure path)
- WebSocket flow (14 tests: lifecycle, binary audio, question events, missing-key degradation, oversized frame drop)
- End-to-end LLM flow (7 tests: streaming, cancel-on-new-question, manual-question bypass, metrics event, missing-LLM graceful)

**Frontend: `tsc -b` + `oxlint src` clean.** Vite build produces 72 KB
gzipped. No unit tests at this layer — behavior is covered by the
end-to-end tests through the real WebSocket + FakeSTT/FakeLLM.

**Provider diagnostic:**

```bash
cd backend && .venv/bin/python scripts/check_providers.py
```

Pings both Deepgram and Gemini against your actual keys, reports status
without logging the keys themselves.


