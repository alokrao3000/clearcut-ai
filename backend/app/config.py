from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLEARCUT_", extra="ignore")

    database_url: str = "sqlite:///./clearcut.db"
    seed_on_startup: bool = True

    # Ingestion
    youtube_api_key: str | None = None
    http_user_agent: str = "ClearCutAI-MetadataBot/0.1 (+https://clearcut.example/bot)"
    http_timeout_seconds: float = 10.0
    http_max_attempts: int = 3
    per_domain_min_interval_seconds: float = 1.0

    # Rights mapping
    auto_assign_min_score: float = 90.0
    auto_assign_min_margin: float = 5.0

    # Background jobs (M3). With use_worker=False the same job functions run inline in the
    # request, which keeps tests and a worker-less dev box working unchanged.
    use_worker: bool = False
    redis_url: str = "redis://localhost:6382"
    job_timeout_seconds: int = 900

    # Script extraction. Without a key the extractor is disabled and scripts still parse
    # into scenes — the LLM step is additive, never load-bearing for ingest.
    anthropic_api_key: str | None = None
    extraction_model: str = "claude-opus-5"
    extraction_max_scene_chars: int = 12_000
    extraction_max_scenes_per_call: int = 6
    script_max_bytes: int = 20 * 1024 * 1024

    # Thumbnail cache (MinIO locally, any S3-compatible store in production).
    thumbnail_cache_enabled: bool = False
    s3_endpoint_url: str = "http://localhost:9002"
    s3_access_key: str = "clearcut"
    s3_secret_key: str = "clearcut-dev-secret"
    s3_bucket: str = "clearcut-thumbnails"
    s3_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()


DISCLAIMER_VERSION = "2026-09-18.v1"
DISCLAIMER_TEXT = (
    "ClearCut AI functions as a workflow automation and sourcing engine. Generated budget "
    "estimates, contact maps, and request documents constitute advisory structural drafts "
    "and do not represent formal legal validation."
)
