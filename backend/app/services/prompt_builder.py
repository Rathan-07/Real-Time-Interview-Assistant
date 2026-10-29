"""Prompt construction for the interview assistant.

Pure functions, zero I/O. Tested in isolation — this is the piece most worth
getting right. A good prompt turns the entire system from "LLM says things"
into "LLM says grounded things in a defendable interview voice."

The anti-hallucination guard is NOT optional. We tell the model:
- Never invent work history, metrics, or company details.
- If the resume lacks evidence, offer a truthful general technical answer OR
  explicitly say you don't have personal evidence for that.

Reality check: a prompt alone does NOT guarantee factual answers. It raises
the bar significantly, but any LLM can still fabricate under pressure.
The README documents this honestly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AnswerMode = Literal["concise", "star"]


@dataclass(frozen=True)
class PromptPayload:
    system: str
    user: str


# ----------------------- shared guards -------------------------


_ANTI_HALLUCINATION = """\
Hard rules you MUST follow:
- Never invent work history, metrics, company names, achievements, dates, \
or technologies the candidate did not list in their resume.
- If the resume does not contain evidence for a claim you'd normally make, \
either (a) answer the question with a truthful general technical explanation \
and skip the personal angle, or (b) explicitly say "my resume does not \
include specific experience with X" and continue with a general answer.
- Do not fabricate numbers (team sizes, latency improvements, revenue impact).
- Do not claim production deployments the candidate did not list.
- If the question asks for something the resume says nothing about, say so \
plainly in one short clause, then give a general technical answer.
"""


_INTERVIEW_VOICE = """\
Speak as the candidate would in a real interview:
- Natural, spoken English (contractions allowed), not a document.
- First person ("I", "my"), not third person.
- No markdown headers, no code fences, no bullet characters at the start of \
lines. Short paragraphs or short dashed bullets ("- ") are fine.
- Match the job description in substance without quoting it back.
"""


# ---------------------- mode-specific guidance ------------------


_CONCISE_INSTRUCTIONS = """\
Length: aim for 60-90 spoken words, or 3-6 short bullets, whichever is \
clearer for this question. Never exceed 120 words.
Structure: lead with the direct answer in one sentence, then one or two \
supporting details from the resume if relevant.
"""


_STAR_INSTRUCTIONS = """\
Use the STAR structure for behavioral questions:
- Situation: 1 sentence of context.
- Task: 1 sentence on what you had to do.
- Action: 2-3 sentences on what YOU specifically did.
- Result: 1 sentence on the outcome.
Only use metrics or outcomes that are actually in the resume. If no \
quantitative result is in the resume, describe the qualitative outcome \
instead of making one up.
Total length: 90-140 spoken words.
"""


# ---------------------- builder ---------------------------------


def build_prompt(
    *,
    resume: str,
    job_description: str,
    question: str,
    mode: AnswerMode,
) -> PromptPayload:
    """Construct system + user strings for a Gemini streaming call.

    `resume` and `job_description` may be empty — in that case the anti-
    hallucination guard still applies and the model should answer generally.
    """
    mode_block = _STAR_INSTRUCTIONS if mode == "star" else _CONCISE_INSTRUCTIONS

    system = (
        "You are an interview coach speaking as the candidate during a live "
        "technical interview. The candidate hears your output as spoken "
        "guidance.\n\n"
        f"{_INTERVIEW_VOICE}\n"
        f"{mode_block}\n"
        f"{_ANTI_HALLUCINATION}"
    )

    resume_block = resume.strip() or "(no resume provided — do not fabricate experience)"
    jd_block = job_description.strip() or "(no job description provided)"

    user = (
        f"Candidate resume / summary:\n---\n{resume_block}\n---\n\n"
        f"Role / job description:\n---\n{jd_block}\n---\n\n"
        f"Interviewer's question:\n---\n{question.strip()}\n---\n\n"
        "Answer now, following the rules above."
    )

    return PromptPayload(system=system, user=user)
