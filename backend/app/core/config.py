"""Settings from environment variables (blueprint section 29.9). Owner: P1."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str
    app_access_token: str

    hindsight_api_url: str = "https://api.hindsight.vectorize.io"
    hindsight_api_key: str | None = None
    hindsight_force_offline: bool = False

    groq_api_key: str | None = None
    llm_model_large: str = "openai/gpt-oss-120b"
    llm_model_small: str = "openai/gpt-oss-20b"

    cors_origin: str = "http://localhost:5173"
    demo_mode: bool = False
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
