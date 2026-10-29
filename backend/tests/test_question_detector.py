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
