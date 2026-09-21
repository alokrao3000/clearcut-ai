"""S3-compatible thumbnail cache (MinIO locally).

Platform thumbnail URLs expire and rate-limit, and hotlinking them leaks which project is
looking at what. Caching a copy fixes both. Failure here is never fatal: the caller keeps
the original URL.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024


@lru_cache
def _client():
    import boto3
    from botocore.config import Config

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
    )


def _ensure_bucket(client, bucket: str) -> None:
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def cache_thumbnail(asset_id: str, source_url: str) -> str | None:
    """Fetch the thumbnail and store it. Returns the cached URL, or None if unavailable."""
    settings = get_settings()
    if not settings.thumbnail_cache_enabled:
        return None

    try:
        response = httpx.get(source_url, timeout=settings.http_timeout_seconds, follow_redirects=True,
                             headers={"User-Agent": settings.http_user_agent})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Thumbnail fetch failed for %s: %s", asset_id, exc)
        return None

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    suffix = ALLOWED_CONTENT_TYPES.get(content_type)
    if suffix is None:
        log.warning("Refusing to cache %s: unexpected content type %r", asset_id, content_type)
        return None
    if len(response.content) > MAX_THUMBNAIL_BYTES:
        log.warning("Refusing to cache %s: %d bytes", asset_id, len(response.content))
        return None

    key = f"assets/{asset_id}{suffix}"
    try:
        client = _client()
        _ensure_bucket(client, settings.s3_bucket)
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=response.content,
                          ContentType=content_type)
    except Exception as exc:  # noqa: BLE001 - boto raises a wide family; none of it is fatal here
        log.warning("Thumbnail upload failed for %s: %s", asset_id, exc)
        return None

    return f"{settings.s3_endpoint_url.rstrip('/')}/{settings.s3_bucket}/{key}"
