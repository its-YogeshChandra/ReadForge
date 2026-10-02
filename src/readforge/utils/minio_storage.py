"""Self-hosted MinIO client configuration."""

from functools import lru_cache
import os

import boto3
from botocore.config import Config


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is not set")
    return value


@lru_cache(maxsize=1)
def get_client():
    return boto3.client(
        "s3",
        endpoint_url=_required("MINIO_ENDPOINT"),
        aws_access_key_id=_required("MINIO_ACCESS_KEY"),
        aws_secret_access_key=_required("MINIO_SECRET_KEY"),
        # Required by AWS request signing; local MinIO has no region setting.
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def get_bucket_name() -> str:
    return _required("MINIO_BUCKET_NAME")
