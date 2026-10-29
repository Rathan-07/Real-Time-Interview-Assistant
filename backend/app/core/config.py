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
    deepgram_model: str = "nova-2"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    question_silence_ms: int = Field(default=800, ge=0, le=10_000)

    frontend_origin: str = "http://localhost:5173"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
