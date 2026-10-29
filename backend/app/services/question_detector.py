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

from collections import deque
from dataclasses import dataclass

# Below this word count we treat the utterance as backchannel / filler rather
# than a question. 3 keeps real short questions ("Explain CORS please",
# "What is REST?") while still rejecting most "yeah okay"-style noise via the
# explicit filler list below.
MIN_QUESTION_WORDS = 3

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
            return None

        chunk = text.strip()
        if chunk:
            self._buffer.append(chunk)

        if not speech_final:
            return None

        utterance = " ".join(self._buffer).strip()
        self._buffer.clear()

        if not utterance or not _looks_like_question(utterance):
            return None

        key = _dedup_key(utterance)
        if key in self._fired:
            return None
        self._fired.append(key)

        qid = f"q_{self._next_id}"
        self._next_id += 1
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
