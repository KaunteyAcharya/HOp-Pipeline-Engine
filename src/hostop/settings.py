"""Environment settings. Secrets come only from .env / environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hostop_db_url: str = "sqlite:///hostop.db"
    hostop_config: str = "config/hostop.yaml"
    hostop_user_agent: str = "HostOpPipelineBot/0.1 (+contact via company website)"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    firecrawl_api_key: str = ""
    apollo_api_key: str = ""
    hunter_api_key: str = ""
    attio_api_key: str = ""
    hostop_api_token: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
