# Top 3 production risks and mitigations

## 1. Third-party provider dependency

The product has zero graceful degradation if Deepgram or Google Gemini is
down. During a single development session I observed Google 503s under load
on `gemini-3.6-flash`, >15 s first-chunk stalls on `gemini-3.1-flash-lite`,
and Deepgram misrecognition that varies minute-to-minute. In an interview
setting these failures surface at the worst possible time.

**Mitigation:** every provider sits behind a 2-method `Protocol`. The next
step is a chain — Deepgram → AssemblyAI on STT, Gemini → Claude on LLM —
triggered by consecutive 5xx, timeout, or empty-response failures. Pair with
basic SLA monitoring (uptime pings, error-rate budgets) and the already-shipped
typed-input bypass so the user is never completely blocked.

## 2. Speech recognition accuracy and fairness

Transcription quality drops sharply for non-American accents, non-native
speakers, and noisy mics. "Explain" is heard as "Expense"; sentences get
split into un-detectable fragments. In production this is a correctness
*and* fairness issue: whole user segments get worse service.

**Mitigation:** expose STT model and language per user (we already have
`DEEPGRAM_MODEL` and `DEEPGRAM_LANGUAGE` as env vars; move to a user
setting). Build a WER regression suite across a corpus of 5–10 accents and
track it over time. For sensitive use cases, run Whisper locally as a
second-pass check on low-confidence transcripts.

## 3. Privacy of candidate data

Raw interview audio, the candidate's resume, and the job description all
flow through third-party APIs. We have no DPAs with Deepgram or Google, no
documented retention policy, and no PII stripping before the LLM call.

**Mitigation:** do not persist audio or transcripts beyond the live session;
negotiate DPAs and EU-residency endpoints with both providers; PII-strip
resumes before LLM calls (names, emails, phone numbers); document a clear
retention and deletion policy in-product.
