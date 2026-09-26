"""Utilities for reading objects stored in a Cloudflare R2 bucket."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
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


def download_files_from_s3(file_name: str, dest_folder: str) -> str:
    """Download an object from R2 to a local path and return that path."""
    dest = Path(dest_folder) / file_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    _r2_client().download_file(_bucket_name(), file_name, str(dest))
    return str(dest)


def create_presigned_url(file_name: str) -> str:
    """Create an R2 GET URL that is valid for one hour."""
    return _r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket_name(), "Key": file_name},
        ExpiresIn=3600,
    )


class Presigned_url:
    type: str
    main_url: str


def submit_ocr_batch(
    presigned_urls: Sequence[Presigned_url],
    *,
    api_key: str | None = None,
    model: str = "mistral-ocr-latest",
) -> dict[str, Any]:
    """Submit one Mistral OCR batch request per presigned document URL.

    Uses inline batch mode, which supports fewer than 10,000 requests. Larger
    batches need to be submitted as an uploaded JSONL file. The result contains
    queued job metadata; retrieve OCR results later using the returned job ID.
    """
    if not presigned_urls:
        raise ValueError("At least one presigned URL is required")
    if len(presigned_urls) >= 10_000:
        raise ValueError("Inline OCR batches support fewer than 10,000 requests")

    key = api_key or os.getenv("MISTRAL_API_KEY")
    if not key:
        raise ValueError("MISTRAL_API_KEY is not set")

    # alternative to : creating batch vec ,iterating over presignedurls , pushing element into batch
    batch_requests = [
        {
            "custom_id": str(index),
            "body": {
                "document": {"type": payload.type, "document_url": payload.main_url},
            },
        }
        for index, payload in enumerate(presigned_urls)
    ]

    payload = json.dumps(
        {
            "endpoint": "/v1/ocr",
            "model": model,
            "requests": batch_requests,
            "timeout_hours": 24,
        }
    ).encode("utf-8")
    request = Request(
        "https://api.mistral.ai/v1/batch/jobs",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Mistral batch submission failed ({error.code}): {detail}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Mistral API: {error.reason}") from error


def list_objects() -> list[dict]:
    """List objects in the configured R2 bucket."""
    response = _r2_client().list_objects_v2(Bucket=_bucket_name())
    return response.get("Contents", [])
