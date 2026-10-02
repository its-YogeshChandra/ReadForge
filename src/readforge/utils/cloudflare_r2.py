"""Cloudflare R2 client configuration."""

from functools import lru_cache
import os

import boto3


def _required(name: str, legacy_name: str) -> str:
    value = (os.getenv(name) or os.getenv(legacy_name, "")).strip()
    if not value:
        raise ValueError(f"{name} is not set")
    return value


@lru_cache(maxsize=1)
def get_client():
    account_id = _required("R2_ACCOUNT_ID", "ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=_required("R2_ACCESS_KEY", "CLOUDFLARE_ACCESS_KEY"),
        aws_secret_access_key=_required(
            "R2_SECRET_ACCESS_KEY", "CLOUDFLARE_SECRET_KEY"
        ),
        region_name="auto",
    )


def get_bucket_name() -> str:
    return _required("R2_BUCKET_NAME", "BUCKET_NAME")
