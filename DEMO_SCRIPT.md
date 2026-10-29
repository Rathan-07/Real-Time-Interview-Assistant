# Demo recording script

**Target length:** 3–5 minutes. Brief says "at least three different questions
live" — this script covers four so you can drop one if time runs over.

**Recording setup:**
- Backend running (`uvicorn ... --reload`), frontend running (`npm run dev`).
- Browser full-screen on the Vite URL. Clear devtools / tabs noise.
- Mic plugged in; test audio levels in the OS before recording.
- Set `GEMINI_MODEL` to whichever model is fastest right now
  (`gemini-3.5-flash` has been reliable in testing). Run
  `python scripts/check_providers.py` first to confirm green.

---

## 00:00–00:30 — Intro + architecture

**Narration:** "This is a POC of a real-time interview assistant. It listens
to the interviewer's question, detects when they've finished asking, and
streams a grounded answer back. One browser WebSocket carries the audio in
and the transcript, detected question, and answer tokens back out."

**On screen:** show the dashboard. Point at the three panels (Transcript,
Detected question, Answer) and the status pills.

---

## 00:30–01:30 — Question 1 (spoken, concise mode)

**Setup:** Mode = **Concise**. Resume and JD panels are already pre-filled.

**Action:** Click **Start Listening**. Allow mic.

**Say clearly, in one breath:**
> "Explain Python generators and when you would use one."

**Narration while waiting:**
"The audio is streaming over the WebSocket to Deepgram. You can see the
interim transcript in grey — that's STT working word-by-word. When the
sentence finalizes and the detector decides it's a real question, you'll
see it in the middle panel, then the Gemini answer streams in token by
token below."

**If STT mishears:** stay calm. Say: *"Streaming STT is non-deterministic
on different voices and mics — I built a typed fallback for exactly this
case. Let me use it to show the pipeline reliably."* Then switch to the
typed input for the same question. **This narration earns points — it's
exactly the kind of trade-off the brief rewards.**

**Point out:** the "N ms to first token" badge next to the Copy button.
Say: *"That's measured server-side on a monotonic clock from question
detection to first chunk — not a hardcoded number."*

---

## 01:30–02:30 — Question 2 (typed, concise mode)

**Setup:** Mode stays **Concise**. Session is already running — do NOT
click Stop between questions. Just type into the input field.

**Type:**
> "What's the difference between REST and GraphQL?"

**Press Enter.**

**Narration while answer streams:**
"Each question gets a fresh prompt — the Session cancels any in-flight
answer when a new question lands, so the UI never shows a stale answer
leaking into a new one. The prompt explicitly includes my resume, the job
description, and an anti-hallucination guard — 'never invent experience'."

**Point out:** the detected-question panel updates to the new question;
the previous answer gets replaced cleanly, no duplication.

---

## 02:30–03:30 — Question 3 (typed, STAR mode)

**Setup:** Switch **Answer mode** dropdown to **STAR (behavioral)**.

**Type:**
> "Tell me about a time you had to debug a hard production bug."

**Press Enter.**

**Narration while answer streams:**
"STAR mode changes the system prompt to Situation / Task / Action /
Result structure. Same adapter, same WebSocket, different mode — no code
change at demo time. The prompt builder is a pure function with unit
tests covering both modes."

**Point out:** the answer follows STAR structure. Point at Copy button.

---

## 03:30–04:15 — Error handling (optional, drop if short on time)

**Narration:** "Let me show what happens on failure. If I stop the
backend uvicorn process while a question is in flight…"

**Action:** [don't actually stop uvicorn mid-demo — too risky] Instead,
point at: "If Deepgram's key is missing, you'd see an error banner saying
`stt_not_configured`. If Gemini 503s, we retry once; if it still fails,
the UI surfaces a dismissible banner and returns to listening. Full
provider failures don't crash the session."

**Point out:** error banner has a dismiss `×`. Status pills return to
`listening` after any failure.

---

## 04:15–04:45 — Close

**Click Stop Listening.**

**Narration:** "Stop releases the mic track, closes the Deepgram
connection, and cancels any in-flight answer. The browser mic indicator
goes away."

**On screen:** show pills all return to `closed` / `stopped` / `prompt`.

**Say:** "Code is in the repo, README has setup and architecture, and
there's a 300-word writeup of top production risks. Thanks for watching."

---

## If something breaks mid-demo

- **STT mishears a question:** switch to typed input, narrate it as a
  deliberate fallback (see Q1 note above). This is a *good* story.
- **Gemini 503 / timeout:** error banner appears. Narrate: *"That's the
  retry logic catching a transient Google 503 — see the error code
  `llm_failed`. In production we'd fall back to a secondary model
  via the LLMProvider protocol."* Hit Ask again on the same question.
- **WebSocket drops:** click Start again to reconnect. Narrate: *"I
  intentionally did not auto-reconnect so the Stop/Start lifecycle stays
  predictable. For production I'd add buffered reconnect — in next-steps
  in the README."*
- **Frozen UI:** refresh the browser. Lose some composure gracefully:
  *"Live demo — one of the risks I called out in the writeup."*

## Final checks before you hit record
- [ ] `.env` has real keys and model is the fast one
- [ ] `scripts/check_providers.py` says all green
- [ ] Backend logs show `model=nova-3, language=en` and
      `gemini: streaming (model=…)` on startup
- [ ] Browser mic permission already granted (no prompt mid-demo)
- [ ] Vite URL is loaded, Resume + JD pre-filled visible
- [ ] Mode dropdown is on Concise for Q1 and Q2
- [ ] Screen recorder is in landscape, 1080p+, audio level test done
- [ ] Phone is on silent
