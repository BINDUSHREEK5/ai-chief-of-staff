"""Centralized application configuration.

Everything is loaded from environment variables (or a local ``.env`` file)
via pydantic-settings. Nothing sensitive is hardcoded, so the same image
can move between dev / staging / prod by changing env vars only.

A note on the Caspian env var names: at the time this project was built,
Caspian's own docs disagreed with each other about what the SDK reads —
the README shows ``COMM_API_KEY`` / ``COMM_BASE_URL``, while ``llms.txt``
and the marketing site show ``CASPIAN_API_KEY`` / ``CASPIAN_BASE_URL``.
Rather than guess, we accept either name (see ``AliasChoices`` below) and
recommend running ``caspian init`` once, which writes whatever your
installed SDK version actually expects into ``.env`` for you.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Caspian (communication layer) -----------------------------------
    caspian_api_key: str = Field(
        default="", validation_alias=AliasChoices("CASPIAN_API_KEY", "COMM_API_KEY")
    )
    caspian_base_url: str = Field(
        default="https://api.trycaspianai.com",
        validation_alias=AliasChoices("CASPIAN_BASE_URL", "COMM_BASE_URL"),
    )
    agent_email_username: str = "chief-of-staff"
    agent_display_name: str = "Chief of Staff"
    telegram_bot_token: str = ""

    # --- LLM (Featherless.ai — OpenAI-compatible inference API) -----------
    featherless_api_key: str = ""
    featherless_base_url: str = "https://api.featherless.ai/v1"
    featherless_model: str = "Qwen/Qwen2.5-7B-Instruct"

    # --- Persistence --------------------------------------------------------
    # SQLite by default. To migrate to Postgres: install `asyncpg`, set
    # DATABASE_URL=postgresql+asyncpg://user:pass@host/db, and restart —
    # SQLAlchemy's async engine + our ORM models handle the dialect switch;
    # see docs/DEPLOYMENT.md for the two SQLite-specific caveats.
    database_url: str = "sqlite+aiosqlite:///./agent.db"

    # --- Agent decision thresholds ------------------------------------------
    urgency_notify_threshold: float = 0.6  # urgency score >= this -> ping Telegram
    sensitive_requires_approval: bool = True  # sensitive replies always need a human
    auto_reply_confidence_threshold: float = 0.85

    # --- Daily summary -------------------------------------------------------
    daily_summary_hour_utc: int = 7

    # --- FastAPI / networking ------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    public_base_url: str = "http://localhost:8000"  # used to build approval links
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()