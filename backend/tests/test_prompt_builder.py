from app.services.prompt_builder import build_prompt


RESUME = (
    "Rathan G — Software Developer. 2 years Python/FastAPI, async/await, "
    "WebSockets, PostgreSQL, Docker. Built a job portal and a RAG assistant. "
    "No production deployment metrics listed."
)
JD = "Software Developer — AI & Real-Time Systems. Streaming, Python, WebSockets."


def test_prompt_includes_resume_jd_and_question():
    p = build_prompt(
        resume=RESUME,
        job_description=JD,
        question="Explain Python generators.",
        mode="concise",
    )
    assert "Rathan" in p.user
    assert "FastAPI" in p.user
    assert "Streaming, Python" in p.user
    assert "Explain Python generators" in p.user


def test_concise_mode_includes_length_guidance():
    p = build_prompt(
        resume=RESUME, job_description=JD, question="x" * 5, mode="concise"
    )
    assert "60-90" in p.system or "60 to 90" in p.system
    assert "star" not in p.system.lower() or "STAR" not in p.system


def test_star_mode_includes_situation_task_action_result():
    p = build_prompt(
        resume=RESUME,
        job_description=JD,
        question="Tell me about a time you failed.",
        mode="star",
    )
    for marker in ("Situation", "Task", "Action", "Result"):
        assert marker in p.system


def test_anti_hallucination_guard_present_in_both_modes():
    for mode in ("concise", "star"):
        p = build_prompt(resume=RESUME, job_description=JD, question="q" * 5, mode=mode)
        assert "Never invent" in p.system
        assert "fabricate" in p.system.lower()
        assert "resume does not" in p.system.lower()


def test_empty_resume_marked_explicitly_in_user_prompt():
    p = build_prompt(
        resume="", job_description=JD, question="Explain CORS.", mode="concise"
    )
    # The LLM must see that the resume is empty, not just a blank block.
    assert "no resume provided" in p.user.lower()


def test_empty_job_description_marked_explicitly():
    p = build_prompt(
        resume=RESUME, job_description="", question="Explain CORS.", mode="concise"
    )
    assert "no job description provided" in p.user.lower()


def test_system_prompt_requests_first_person_interview_voice():
    p = build_prompt(
        resume=RESUME, job_description=JD, question="q" * 5, mode="concise"
    )
    assert "First person" in p.system or "first person" in p.system
    assert "spoken" in p.system.lower()


def test_prompt_is_pure_same_inputs_same_outputs():
    args = dict(resume=RESUME, job_description=JD, question="q" * 5, mode="concise")
    a = build_prompt(**args)
    b = build_prompt(**args)
    assert a == b
