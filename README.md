# Real-Time Interview Assistant

Streaming speech-to-text → question detection → streaming LLM answer, delivered to a React UI over a single browser WebSocket.

**Status:** scaffolding (Phase 0). A proper README with setup, architecture, demo plan, and limitations lands in Phase 7.

## Stack
- Backend: Python 3.12 + FastAPI + asyncio
- Frontend: React + TypeScript + Vite
- STT: Deepgram live streaming
- LLM: Google Gemini (streaming)
- Transport: single browser-to-backend WebSocket

## Layout
```
backend/   FastAPI app, provider adapters, question detection, tests
frontend/  Vite React-TS dashboard
```
