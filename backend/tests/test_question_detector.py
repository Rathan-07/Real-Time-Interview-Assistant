from app.services.question_detector import QuestionDetector


def _emit_full_utterance(d: QuestionDetector, text: str):
    """Simulate the two-event Deepgram pattern for a complete utterance:
    one is_final chunk, then speech_final on an empty follow-up or on the
    same text. We model it as a single is_final=True, speech_final=True
    event for brevity — the detector treats either shape the same way.
    """
    return d.observe(text, is_final=True, speech_final=True)


# ------------------- positives -------------------


def test_detects_wh_question():
    d = QuestionDetector()
    out = _emit_full_utterance(d, "How would you design a URL shortener?")
    assert out is not None
    assert "URL" in out.text


def test_detects_explain_prefix():
    d = QuestionDetector()
    out = _emit_full_utterance(d, "Explain Python generators and when you'd use one.")
    assert out is not None


def test_detects_tell_me_about():
    d = QuestionDetector()
    out = _emit_full_utterance(d, "Tell me about a time you had to debug a production incident.")
    assert out is not None


def test_detects_difference_between():
    d = QuestionDetector()
    out = _emit_full_utterance(d, "What's the difference between a thread and a process?")
    assert out is not None


def test_detects_question_mark_without_wh_prefix():
    d = QuestionDetector()
    out = _emit_full_utterance(d, "You've worked on async code before?")
    assert out is not None


# ------------------- negatives -------------------


def test_rejects_short_filler():
    d = QuestionDetector()
    assert _emit_full_utterance(d, "yeah okay") is None
    assert _emit_full_utterance(d, "right got it") is None
    assert _emit_full_utterance(d, "mhm") is None


def test_rejects_small_talk_how_are_you():
    d = QuestionDetector()
    assert _emit_full_utterance(d, "How are you doing today?") is None


def test_rejects_small_talk_nice_to_meet_you():
    d = QuestionDetector()
    assert _emit_full_utterance(d, "Nice to meet you, Rathan.") is None


def test_rejects_single_word_imperatives():
    d = QuestionDetector()
    assert _emit_full_utterance(d, "Explain.") is None  # too short


def test_rejects_non_final_events():
    d = QuestionDetector()
    out = d.observe("How would you design", is_final=False, speech_final=False)
    assert out is None


# -------------- buffering across is_final partials ---------------


def test_buffers_multiple_is_final_segments_until_speech_final():
    d = QuestionDetector()
    first = d.observe("Explain", is_final=True, speech_final=False)
    second = d.observe("Python generators and when you'd use one.", is_final=True, speech_final=True)
    assert first is None  # buffered
    assert second is not None
    assert "Python generators" in second.text


# -------------- dedup ---------------


def test_identical_utterance_does_not_fire_twice():
    d = QuestionDetector()
    first = _emit_full_utterance(d, "Explain how garbage collection works in Python.")
    second = _emit_full_utterance(d, "Explain how garbage collection works in Python.")
    assert first is not None
    assert second is None  # dedup'd


def test_dedup_is_case_and_punctuation_insensitive():
    d = QuestionDetector()
    first = _emit_full_utterance(d, "Explain how garbage collection works in Python.")
    second = _emit_full_utterance(d, "explain HOW garbage collection works in python")
    assert first is not None
    assert second is None


def test_dedup_window_allows_old_question_to_return_after_others():
    d = QuestionDetector(dedup_window=2)
    first = _emit_full_utterance(d, "Explain Python generators.")
    assert first is not None
    assert _emit_full_utterance(d, "Walk me through a load balancer design.") is not None
    assert _emit_full_utterance(d, "Tell me about an outage you handled.") is not None
    # First question falls out of the dedup window and may fire again.
    again = _emit_full_utterance(d, "Explain Python generators.")
    assert again is not None


# -------------- reset ---------------


def test_reset_clears_buffer_and_dedup():
    d = QuestionDetector()
    assert _emit_full_utterance(d, "Explain Python generators.") is not None
    d.reset()
    # Same question fires again after reset — state is gone.
    assert _emit_full_utterance(d, "Explain Python generators.") is not None


def test_reset_clears_pending_buffer():
    d = QuestionDetector()
    d.observe("Explain", is_final=True, speech_final=False)
    d.reset()
    # The lingering "Explain" buffer should not leak into the next utterance.
    out = d.observe("Python generators work how exactly?", is_final=True, speech_final=True)
    assert out is not None
    assert out.text.startswith("Python generators")


# -------------- ids ---------------


def test_question_ids_increment():
    d = QuestionDetector()
    a = _emit_full_utterance(d, "Explain Python generators and iterators.")
    b = _emit_full_utterance(d, "Walk me through a URL shortener design.")
    assert a is not None and b is not None
    assert a.id != b.id
    assert a.id.startswith("q_") and b.id.startswith("q_")


# -------- real-world STT-mishearing cases (reproducing live issues) -----


def test_mishearing_noun_phrase_does_not_fire():
    """Deepgram once transcribed 'Explain Python generators' as
    'In Python, Genetas.' — the detector must NOT fire on that because it
    doesn't start with a WH/imperative and isn't question-shaped."""
    d = QuestionDetector()
    assert _emit_full_utterance(d, "In Python, Genetas.") is None


def test_mishearing_short_noun_phrase_fragment_does_not_fire():
    d = QuestionDetector()
    assert _emit_full_utterance(d, "Python classes") is None  # no verb, no WH
    assert _emit_full_utterance(d, "The code") is None


def test_two_word_imperative_question_still_fires():
    """Deepgram sometimes splits 'Explain Python generators' into two
    speech_final chunks. The first chunk 'Explain Python' is a 2-word
    legitimate imperative question and should fire."""
    d = QuestionDetector()
    out = _emit_full_utterance(d, "Explain Python.")
    assert out is not None
    assert "Explain Python" in out.text


def test_two_word_what_question_fires():
    d = QuestionDetector()
    out = _emit_full_utterance(d, "What's REST?")
    assert out is not None


# -------- punctuation fallback (speech_final sometimes never arrives) ------


def test_sentence_punctuation_flushes_even_without_speech_final():
    """Live bug: Deepgram sent is_final=True with trailing '.' but never a
    speech_final=True. The detector should flush on sentence-ending
    punctuation as a fallback."""
    d = QuestionDetector()
    out = d.observe(
        "Explain Python generators.",
        is_final=True,
        speech_final=False,
    )
    assert out is not None
    assert out.text == "Explain Python generators."


def test_sentence_without_terminal_punct_still_buffers():
    d = QuestionDetector()
    out = d.observe(
        "Explain Python generators",  # no trailing punct
        is_final=True,
        speech_final=False,
    )
    assert out is None  # keep waiting


def test_punctuation_flush_still_rejects_non_question_shaped():
    """Even with punctuation flush, 'Expense scopes in JavaScript.' is not
    question-shaped so the detector must still reject it."""
    d = QuestionDetector()
    out = d.observe(
        "Expense scopes in JavaScript.",
        is_final=True,
        speech_final=False,
    )
    assert out is None  # correctly rejected — not an "Explain/How/What..." sentence


# -------- Deepgram over-eager splitting (seen live) -----


def test_split_question_rejoins_across_chunks():
    """Live bug: Deepgram split 'Explain scopes in JavaScript' into
    'Explain.' + 'Scopes in JavaScript.' as two speech_final=False
    is_final events. The detector should buffer the 1-word 'Explain.',
    accept the second chunk, join them, strip the stray '.', and fire."""
    d = QuestionDetector()
    first = d.observe("Explain.", is_final=True, speech_final=False)
    assert first is None  # 1 word → defer, do not flush yet
    second = d.observe("Scopes in JavaScript.", is_final=True, speech_final=False)
    assert second is not None
    assert "Explain" in second.text
    assert "Scopes in JavaScript" in second.text
    # The stray '.' between the two chunks must have been stripped.
    assert "Explain. Scopes" not in second.text


def test_single_word_sentence_defers_until_more_arrives():
    """If the user says only 'Explain.' once, the detector must NOT fire
    (1 word < MIN_QUESTION_WORDS). The buffer holds it, waiting for more.
    If no second chunk ever arrives, the session's reset() clears state."""
    d = QuestionDetector()
    assert d.observe("Explain.", is_final=True, speech_final=False) is None
    # No crash, no fire. Buffer has 1 entry.
    assert len(d._buffer) == 1  # type: ignore[attr-defined]


def test_buffer_is_capped_to_max_chunks():
    from app.services.question_detector import MAX_BUFFER_CHUNKS

    d = QuestionDetector()
    for i in range(MAX_BUFFER_CHUNKS + 10):
        d.observe(f"word{i}", is_final=True, speech_final=False)
    assert len(d._buffer) <= MAX_BUFFER_CHUNKS  # type: ignore[attr-defined]
