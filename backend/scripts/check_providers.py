"""Dev diagnostic — run against your real .env to verify both providers work.

What it checks:
1. Deepgram: lists projects (any 200 means the key is live).
2. Gemini: calls the configured model with a 1-token prompt (any text in
   response means model + key are live).

Does NOT run streaming audio / full flow — that lives in uvicorn + tests.
Does NOT print or log key values.

Run with:
    cd backend
    .venv/bin/python scripts/check_providers.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow `python scripts/check_providers.py` from the backend/ dir to find `app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _tick(label: str, ok: bool, detail: str = "") -> None:
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {label}" + (f"  — {detail}" if detail else ""))


async def check_deepgram(api_key: str) -> bool:
    try:
        import httpx
    except ImportError:
        _tick("deepgram", False, "httpx not installed")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {api_key}"},
            )
    except Exception as e:
        _tick("deepgram", False, f"network error: {type(e).__name__}")
        return False

    if r.status_code == 200:
        projects = r.json().get("projects", [])
        _tick("deepgram", True, f"key valid, {len(projects)} project(s)")
        return True
    if r.status_code == 401:
        _tick("deepgram", False, "401 — key is invalid or revoked")
    else:
        _tick("deepgram", False, f"HTTP {r.status_code}")
    return False


async def check_gemini(api_key: str, model: str) -> bool:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        _tick("gemini", False, "google-genai not installed")
        return False

    client = genai.Client(api_key=api_key)
    try:
        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=5),
            ),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        _tick("gemini", False, f"20 s timeout — model {model!r} probably hangs")
        return False
    except Exception as e:
        msg = str(e).replace(api_key, "<redacted>")
        _tick("gemini", False, f"{type(e).__name__}: {msg[:160]}")
        return False

    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        _tick("gemini", False, f"empty response for model {model!r}")
        return False
    _tick("gemini", True, f"model {model!r} responded ({len(text)} chars)")
    return True


async def main() -> int:
    # Import inside main so a missing dep doesn't crash before we can report.
    try:
        from app.core.config import get_settings
    except Exception as e:
        print(f"could not load Settings: {e}")
        return 2

    s = get_settings()

    print("provider check (keys never printed)")
    print("-" * 40)

    missing_dg = not s.deepgram_api_key
    missing_gm = not s.gemini_api_key
    _tick("deepgram key present", not missing_dg)
    _tick("gemini key present", not missing_gm)
    print(f"       deepgram model = {s.deepgram_model}")
    print(f"       gemini model   = {s.gemini_model}")
    print()

    results = []
    if not missing_dg:
        results.append(await check_deepgram(s.deepgram_api_key))
    if not missing_gm:
        results.append(await check_gemini(s.gemini_api_key, s.gemini_model))

    print("-" * 40)
    if all(results) and results:
        print("all providers reachable")
        return 0
    print("one or more providers failed — see above")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
