from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    # Required, no defaults: a missing value fails at startup instead of silently hitting the wrong DB.
    mongodb_uri: str
    mongodb_db_name: str
    gemini_api_key: str = ""
    google_maps_api_key: str = ""
    ticketmaster_api_key: str = ""
    eia_api_key: str = ""
    here_api_key: str = ""
    nws_user_agent: str = "MAPAY (contact@example.com)"
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
