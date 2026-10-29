from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    deepgram_api_key: str = ""
    # nova-3 is Deepgram's newest general-purpose STT model (as of 2026) with
    # measurably better accuracy on non-American English accents than nova-2.
    deepgram_model: str = "nova-3"
    # Language hint. "en" (general English) is more accent-tolerant than
    # "en-US"; "multi" lets Deepgram auto-detect but hurts short utterances.
    deepgram_language: str = "en"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    question_silence_ms: int = Field(default=1200, ge=0, le=10_000)

    frontend_origin: str = "http://localhost:5173"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
