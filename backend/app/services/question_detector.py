"""Deterministic question detector.

Purpose: decide whether a finalized stretch of transcript is a question we
should answer. Deliberately NOT an LLM — a classifier here would add 300+ ms
of first-token latency and cost on every pause, for marginal accuracy over a
heuristic. The things we miss (rhetorical questions, abrupt follow-ups) are
not worth paying a classifier tax for in a POC.

Design:
- Only act on `is_final` segments from Deepgram (interim text is too volatile).
- Buffer finalized segments until Deepgram signals `speech_final` — that's the
  end-of-utterance marker driven by endpointing=QUESTION_SILENCE_MS.
- On speech_final, assemble the buffered utterance and classify with cheap rules.
- Dedup across the last few utterances to protect against Deepgram re-finalizing.

Thresholds and word lists are configurable at the top of the file; heuristics
are imperfect by design and documented as such.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Below this word count we treat the utterance as backchannel / filler rather
# than a question. 2 accepts legit short questions ("Explain generators",
# "What's REST") that Deepgram often splits off a longer utterance at a mid-
# sentence pause. Short noise ("yeah okay", "mhm") is still caught by the
# explicit filler blacklist and the small-talk prefix list below.
MIN_QUESTION_WORDS = 2

# Hard cap on how many chunks we hold while buffering across is_final events
# without ever seeing speech_final=True or an acceptable punctuation flush.
# Prevents unbounded memory growth from a non-stop talker.
MAX_BUFFER_CHUNKS = 20

# Normalized phrases that we always reject even if they match a WH-start.
_SMALL_TALK_PREFIXES: tuple[str, ...] = (
    "how are you",
    "how's it going",
    "how have you been",
    "how do you do",
    "nice to meet you",
    "good morning",
    "good afternoon",
    "good evening",
    "thanks for",
    "thank you for",
)

# Full-utterance filler — single acknowledgements, backchannel.
_FILLER_UTTERANCES: frozenset[str] = frozenset(
    {
        "ok",
        "okay",
        "yeah",
        "yes",
        "no",
        "sure",
        "right",
        "got it",
        "mhm",
        "uh huh",
        "alright",
        "cool",
        "makes sense",
        "right right",
    }
)

_WH_WORDS: frozenset[str] = frozenset(
    {"what", "why", "how", "when", "where", "which", "who", "whose"}
)

# Multi-word interview-question starts. Checked as prefix matches.
_INTERVIEW_PREFIXES: tuple[str, ...] = (
    "explain ",
    "describe ",
    "walk me through ",
    "walk us through ",
    "can you ",
    "could you ",
    "would you ",
    "tell me about ",
    "tell us about ",
    "give me an example",
    "give us an example",
    "difference between ",
    "what's the difference",
    "how would you ",
    "how do you ",
    "how did you ",
)


@dataclass(frozen=True)
class DetectedQuestion:
    id: str
    text: str


class QuestionDetector:
    """Stateful detector. One instance per interview session."""

    def __init__(self, dedup_window: int = 3) -> None:
        self._buffer: list[str] = []
        self._fired: deque[str] = deque(maxlen=dedup_window)
        self._next_id = 1

    def observe(
        self, text: str, is_final: bool, speech_final: bool
    ) -> DetectedQuestion | None:
        """Feed a transcript event. Returns a question iff this event ended
        a complete utterance that looks like a real interview question.

        - Interim events are ignored.
        - Finalized but non-endpointed events are buffered for later.
        """
        if not is_final:
            # Not strictly a problem but very noisy — keep at DEBUG.
            log.debug("detector: skipping interim text=%r", text)
            return None

        chunk = text.strip()
        if chunk:
            self._buffer.append(chunk)
            if len(self._buffer) > MAX_BUFFER_CHUNKS:
                # Drop the oldest chunk so the buffer stays bounded.
                self._buffer.pop(0)

        # Fallback flush: Deepgram sometimes finalizes a sentence (is_final=T)
        # with trailing punctuation but never sends speech_final=T if the
        # user stops talking abruptly, OR it over-eagerly splits one spoken
        # question into several speech_final=False chunks (seen live:
        # 'Explain.' then 'Scopes in JavaScript.'). So the rule is:
        # - speech_final=T always flushes
        # - sentence-ending punctuation flushes ONLY IF the accumulated buffer
        #   has >= MIN_QUESTION_WORDS so we don't flush a 1-word fragment
        #   that should merge with the next chunk.
        sentence_ended = chunk and chunk[-1] in {".", "?", "!"}
        total_words = sum(len(c.split()) for c in self._buffer)

        if not speech_final:
            if not sentence_ended:
                log.info(
                    "detector: buffering (is_final=T, speech_final=F) text=%r "
                    "buffer_now=%r",
                    text,
                    self._buffer,
                )
                return None
            if total_words < MIN_QUESTION_WORDS:
                log.info(
                    "detector: deferring punctuation-flush — only %d word(s) "
                    "buffered, waiting for more. buffer=%r",
                    total_words,
                    self._buffer,
                )
                return None
            log.info(
                "detector: punctuation-flush fallback (speech_final was False)"
            )

        # Join buffer chunks, stripping stray terminal punctuation from all
        # but the last chunk so Deepgram's over-eager "Explain." + "Scopes."
        # splits merge back into a prefix-matchable "Explain Scopes.".
        cleaned: list[str] = []
        last_idx = len(self._buffer) - 1
        for i, c in enumerate(self._buffer):
            if i < last_idx:
                cleaned.append(c.rstrip(".!?,;:").strip())
            else:
                cleaned.append(c)
        utterance = " ".join(cleaned).strip()
        self._buffer.clear()

        if not utterance:
            log.info("detector: speech_final with empty buffer — dropping")
            return None

        if not _looks_like_question(utterance):
            log.info(
                "detector: REJECTED (not question-shaped) utterance=%r reason=%s",
                utterance,
                _reject_reason(utterance),
            )
            return None

        key = _dedup_key(utterance)
        if key in self._fired:
            log.info("detector: DEDUP'd utterance=%r", utterance)
            return None
        self._fired.append(key)

        qid = f"q_{self._next_id}"
        self._next_id += 1
        log.info("detector: FIRED id=%s utterance=%r", qid, utterance)
        return DetectedQuestion(id=qid, text=utterance)

    def reset(self) -> None:
        """Drop all state. Called on Stop so a new session starts clean."""
        self._buffer.clear()
        self._fired.clear()
        self._next_id = 1


# ------------------------- heuristics --------------------------------------


def _looks_like_question(text: str) -> bool:
    stripped = text.strip()
    lowered = stripped.lower().rstrip(".!").rstrip()

    if lowered in _FILLER_UTTERANCES:
        return False

    for prefix in _SMALL_TALK_PREFIXES:
        if lowered.startswith(prefix):
            return False

    words = lowered.split()
    if len(words) < MIN_QUESTION_WORDS:
        return False

    if stripped.endswith("?"):
        return True

    if words[0] in _WH_WORDS:
        return True

    for prefix in _INTERVIEW_PREFIXES:
        if lowered.startswith(prefix):
            return True

    return False


def _dedup_key(text: str) -> str:
    """Case/punctuation-insensitive key so Deepgram re-finalizations collapse."""
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").strip()


def _reject_reason(text: str) -> str:
    """Explain why `text` was rejected — used only for diagnostic logs."""
    stripped = text.strip()
    lowered = stripped.lower().rstrip(".!").rstrip()
    if lowered in _FILLER_UTTERANCES:
        return "filler-blacklist"
    for prefix in _SMALL_TALK_PREFIXES:
        if lowered.startswith(prefix):
            return f"small-talk-prefix({prefix!r})"
    words = lowered.split()
    if len(words) < MIN_QUESTION_WORDS:
        return f"too-short({len(words)}<{MIN_QUESTION_WORDS})"
    if stripped.endswith("?"):
        return "unexpected (ends-with-?)"  # should have fired
    if words[0] in _WH_WORDS:
        return "unexpected (WH-start)"  # should have fired
    return "no-prefix-match"
