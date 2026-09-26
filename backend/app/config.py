from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    # Required, no defaults: a missing value fails at startup instead of silently hitting the wrong DB.
    mongodb_uri: str
    mongodb_db_name: str
    # Gemini: AI Studio key by default; set GOOGLE_GENAI_USE_VERTEXAI=true to use Vertex AI instead
    # (see AGENTS.md "Gemini fallback plan"). Only app/agents/genai_client.py reads these.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    google_genai_use_vertexai: bool = False
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    # Local dev only. On Cloud Run leave unset: the attached service account authenticates.
    google_application_credentials: str = ""
    google_maps_api_key: str = ""
    ticketmaster_api_key: str = ""
    eia_api_key: str = ""
    here_api_key: str = ""
    nws_user_agent: str = "MAPAY (contact@example.com)"
    # Comma-separated. Defaults cover the browser dev server and the iOS Capacitor web view
    # (capacitor://localhost); deployments append the Vercel domain via CORS_ORIGINS.
    cors_origins: str = "capacitor://localhost,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
