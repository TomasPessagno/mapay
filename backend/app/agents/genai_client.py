"""The one place that decides how Gemini is reached: AI Studio key (default) or Vertex AI (fallback).

Switching is config only -- no caller changes. See AGENTS.md "Gemini fallback plan".
"""
import logging

from google import genai
from google.genai import errors

from app.config import get_settings

logger = logging.getLogger(__name__)


def gemini_configured() -> bool:
    s = get_settings()
    return bool(s.google_cloud_project) if s.google_genai_use_vertexai else bool(s.gemini_api_key)


def get_genai_client() -> genai.Client:
    s = get_settings()
    if not s.google_genai_use_vertexai:
        return genai.Client(api_key=s.gemini_api_key)

    if not s.google_cloud_project:
        raise ValueError("GOOGLE_GENAI_USE_VERTEXAI=true but GOOGLE_CLOUD_PROJECT is not set")
    credentials = None
    if s.google_application_credentials:
        # Settings are read from .env, not os.environ, so hand the file to the SDK explicitly.
        # Accepts a service account key or the user login from `gcloud auth application-default login`.
        import google.auth

        credentials, _ = google.auth.load_credentials_from_file(
            s.google_application_credentials, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    # credentials=None -> Application Default Credentials (the Cloud Run service account).
    return genai.Client(
        vertexai=True, project=s.google_cloud_project, location=s.google_cloud_location, credentials=credentials
    )


def log_api_error(context: str, exc: errors.APIError) -> None:
    if exc.code in (402, 429):  # 402: prepaid credits depleted, 429: quota/rate limit
        backend = "Vertex AI" if get_settings().google_genai_use_vertexai else "AI Studio"
        logger.error("%s: Gemini out of quota/credits on %s (HTTP %s) -- see AGENTS.md 'Gemini fallback plan'",
                     context, backend, exc.code)
    else:
        logger.error("%s: Gemini API error %s: %s", context, exc.code, exc.message)
