"""Select the configured S3-compatible media bucket provider."""

import os

from readforge.utils import cloudflare_r2, minio_storage


def get_provider() -> str:
    provider = os.getenv("MEDIA_BUCKET_PROVIDER", "cloudflare").strip().lower()
    if provider not in {"cloudflare", "minio"}:
        raise ValueError("MEDIA_BUCKET_PROVIDER must be 'cloudflare' or 'minio'")
    return provider


def get_client():
    if get_provider() == "minio":
        return minio_storage.get_client()
    return cloudflare_r2.get_client()


def get_bucket_name() -> str:
    if get_provider() == "minio":
        return minio_storage.get_bucket_name()
    return cloudflare_r2.get_bucket_name()
