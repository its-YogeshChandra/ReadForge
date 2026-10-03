"""Select the configured S3-compatible media bucket provider."""

import os

from botocore.exceptions import BotoCoreError, ClientError

from readforge.utils import cloudflare_r2, minio_storage


_UNAVAILABLE_CODES = {
    "AccessDenied",
    "ExpiredRequest",
    "InternalError",
    "NoSuchBucket",
    "NotEntitled",
    "RequestTimeout",
    "ServiceUnavailable",
    "SignatureDoesNotMatch",
    "SlowDown",
    "TooManyRequests",
    "Unauthorized",
}


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


def is_unavailable_error(error: BotoCoreError | ClientError) -> bool:
    """Return whether a storage error represents an unavailable dependency."""
    if isinstance(error, BotoCoreError):
        return True

    status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    error_code = error.response.get("Error", {}).get("Code")
    return (
        status_code == 429
        or (isinstance(status_code, int) and status_code >= 500)
        or error_code in _UNAVAILABLE_CODES
    )
