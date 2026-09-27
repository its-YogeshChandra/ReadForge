"""Utilities for reading objects stored in a Cloudflare R2 bucket."""

from pathlib import Path
import os

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()


def _r2_client():
    """Create an R2 client from the standard Cloudflare credential variables."""
    account_id = os.getenv("ACCOUNT_ID")
    access_key = os.getenv("CLOUDFLARE_ACCESS_KEY")
    secret_key = os.getenv("CLOUDFLARE_SECRET_KEY")
    if not all((account_id, access_key, secret_key)):
        raise ValueError(
            "ACCOUNT_ID, CLOUDFLARE_ACCESS_KEY, and CLOUDFLARE_SECRET_KEY must be set"
        )

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def _bucket_name() -> str:
    bucket = os.getenv("BUCKET_NAME")
    if not bucket:
        raise ValueError("BUCKET_NAME is not set")
    return bucket


async def is_file_exist(file_name: str) -> bool:
    """Return whether ``file_name`` exists in the configured R2 bucket.

    Missing-object responses return ``False``. Other R2 errors, such as
    authentication or network failures, are raised to the caller.
    """
    try:
        _r2_client().head_object(Bucket=_bucket_name(), Key=file_name)
        return True
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error_code in {"404", "NoSuchKey", "NotFound"} or status_code == 404:
            return False
        raise


def download_files_from_s3(file_name: str, dest_folder: str) -> str:
    """Download an object from R2 to a local path and return that path."""
    dest = Path(dest_folder) / file_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    _r2_client().download_file(_bucket_name(), file_name, str(dest))
    return str(dest)


def create_presigned_url(file_name: str) -> str:
    """Create an R2 GET URL that is valid for one hour."""
    # check if file actually exist
    return _r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket_name(), "Key": file_name},
        ExpiresIn=3600,
    )


def list_objects() -> list[dict]:
    """List objects in the configured R2 bucket."""
    response = _r2_client().list_objects_v2(Bucket=_bucket_name())
    return response.get("Contents", [])
