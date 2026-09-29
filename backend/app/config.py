"""Application settings, loaded once from the environment and the repository-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # --- Storage -------------------------------------------------------------
    database_url: str = "sqlite:///./projectpulse-demo.db"

    # --- Hindsight Cloud -----------------------------------------------------
    hindsight_api_key: str | None = None
    hindsight_base_url: str = Field(
        default="https://api.hindsight.vectorize.io",
        validation_alias=AliasChoices("HINDSIGHT_API_URL", "HINDSIGHT_BASE_URL"),
    )
    hindsight_force_offline: bool = False

    # --- LLM (Groq or any OpenAI-compatible endpoint) -------------------------
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"  # legacy /agent-answer endpoint only
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model_large: str = "openai/gpt-oss-120b"
    llm_model_small: str = "openai/gpt-oss-20b"

    # --- API surface ---------------------------------------------------------
    app_access_token: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:5176"
    # Vite chooses the next open local port during development. Keep this narrow
    # to common Vite ports while allowing both browser host spellings.
    cors_origin_regex: str | None = r"^https?://(localhost|127\.0\.0\.1):517[3-9]$"
    demo_mode: bool = True
    max_body_bytes: int = 1_048_576
    llm_rate_limit_per_minute: int = 30
    log_level: str = "INFO"

    # --- Governance ----------------------------------------------------------
    review_due_days: int = 180
    retry_worker_interval_seconds: float = 30.0
    retry_max_attempts: int = 8
    enable_background_jobs: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def hindsight_configured(self) -> bool:
        return bool(self.hindsight_api_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
