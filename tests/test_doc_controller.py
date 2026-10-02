"""Integration tests for ``POST /documents``.

The success cases use the configured media bucket, PostgreSQL, and Redis
services. Set ``EXISTING_MEDIA_SHA256`` to the real SHA-256 digest before
running those live cases. The checksum rejection case is isolated with mocks.

Run with: uv run --with pytest pytest tests/test_doc_controller.py -v
"""

from collections.abc import Iterator
import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import readforge.controllers.doc_controller as controller
from readforge.server import app
from readforge.utils.reading_util import FileTamperingError

# Replace this with an object key that currently exists in the media bucket.
EXISTING_MEDIA_FILE = "Fintech-Edge-April-2018.pdf"

# Replace this with an object key that definitely does not exist in the bucket.
MISSING_MEDIA_FILE = "REPLACE_WITH_MISSING_MEDIA_FILE.pdf"
VALID_CHECKSUM = os.getenv("EXISTING_MEDIA_SHA256", "0" * 64)


# ── helpers ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def api_client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _new_idempotency_key() -> str:
    return uuid4().hex[:20]


def _require_real_checksum() -> None:
    if VALID_CHECKSUM == "0" * 64:
        pytest.skip("Set EXISTING_MEDIA_SHA256 to run live R2 success tests")


def _assert_validation_error(
    response: Any,
    *,
    field: str,
    error_type: str,
    message: str,
) -> None:
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    errors = response.json()["detail"]
    assert len(errors) == 1
    assert errors[0]["loc"] == ["body", field]
    assert errors[0]["type"] == error_type
    assert errors[0]["msg"] == message


# ═══════════════════════════════════════════════════════════════════════════
# 1. POSITIVE TESTS — requests must be accepted
# ═══════════════════════════════════════════════════════════════════════════


# what : Queues a real object from the configured media bucket and Redis.
# why   : The complete HTTP, storage, signing, and queueing flow must return a usable job ID.
def test_upload_existing_document_returns_202(api_client: TestClient) -> None:
    _require_real_checksum()
    response = api_client.post(
        "/documents",
        json={
            "file_name": EXISTING_MEDIA_FILE,
            "idem_key": _new_idempotency_key(),
            "checksum": VALID_CHECKSUM,
        },
    )

    assert response.status_code == 202
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"success", "message", "job_id", "document_id"}
    assert body["success"] is True
    assert body["message"] == "Document queued for processing"
    assert UUID(body["job_id"])
    assert UUID(body["document_id"])


# what : Sends the same real request twice with one idempotency key.
# why   : ADDED - retries must return the original Redis job instead of creating duplicates.
def test_repeated_idempotency_key_returns_same_job(
    api_client: TestClient,
) -> None:
    _require_real_checksum()
    idem_key = _new_idempotency_key()
    payload = {
        "file_name": EXISTING_MEDIA_FILE,
        "idem_key": idem_key,
        "checksum": VALID_CHECKSUM,
    }

    first_response = api_client.post("/documents", json=payload)
    second_response = api_client.post("/documents", json=payload)

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first_response.json()["job_id"] == second_response.json()["job_id"]
    assert (
        first_response.json()["document_id"]
        == second_response.json()["document_id"]
    )


# what : Queues a real document with an idempotency key at the twenty-byte limit.
# why   : ADDED - the maximum valid key size must remain accepted by the API and Redis.
def test_upload_accepts_twenty_byte_idempotency_key(
    api_client: TestClient,
) -> None:
    _require_real_checksum()
    response = api_client.post(
        "/documents",
        json={
            "file_name": EXISTING_MEDIA_FILE,
            "idem_key": _new_idempotency_key(),
            "checksum": VALID_CHECKSUM,
        },
    )

    assert response.status_code == 202
    assert UUID(response.json()["job_id"])


# ═══════════════════════════════════════════════════════════════════════════
# 2. NEGATIVE TESTS — requests must fail in the specified way
# ═══════════════════════════════════════════════════════════════════════════


# what : Requests an object key that does not exist in the media bucket.
# why   : Missing documents must return 404 and must not be queued in Redis.
def test_missing_document_returns_404(api_client: TestClient) -> None:
    response = api_client.post(
        "/documents",
        json={
            "file_name": MISSING_MEDIA_FILE,
            "idem_key": _new_idempotency_key(),
            "checksum": VALID_CHECKSUM,
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "message": f"File '{MISSING_MEDIA_FILE}' was not found",
        "job_id": None,
        "document_id": None,
    }


# what : Rejects a media object whose stored checksum differs from the request.
# why   : A mismatched object must not be persisted or queued for processing.
def test_checksum_metadata_mismatch_returns_409(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def object_exists(_file_name: str) -> bool:
        return True

    def reject_checksum(_file_name: str, _checksum: str) -> None:
        raise FileTamperingError("checksum mismatch")

    monkeypatch.setattr(controller, "is_file_exist", object_exists)
    monkeypatch.setattr(
        controller,
        "verify_object_checksum_metadata",
        reject_checksum,
    )

    response = api_client.post(
        "/documents",
        json={
            "file_name": "documents/tampered.pdf",
            "idem_key": _new_idempotency_key(),
            "checksum": "0" * 64,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "message": "File integrity verification failed",
        "job_id": None,
        "document_id": None,
    }


# what : Rejects a request that omits the required idempotency key.
# why   : Every queued request needs an idempotency identity to prevent duplicate work.
def test_missing_idempotency_key_returns_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/documents",
        json={"file_name": EXISTING_MEDIA_FILE, "checksum": VALID_CHECKSUM},
    )

    _assert_validation_error(
        response,
        field="idem_key",
        error_type="missing",
        message="Field required",
    )


# what : Rejects an idempotency key longer than twenty UTF-8 bytes.
# why   : The controller contract must enforce the Redis key-size policy.
def test_oversized_idempotency_key_returns_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/documents",
        json={
            "file_name": EXISTING_MEDIA_FILE,
            "idem_key": "a" * 21,
            "checksum": VALID_CHECKSUM,
        },
    )

    _assert_validation_error(
        response,
        field="idem_key",
        error_type="value_error",
        message="Value error, idem_key must not exceed 20 bytes",
    )


# what : Applies the idempotency limit to encoded bytes rather than character count.
# why   : ADDED - multibyte Unicode input must not bypass the twenty-byte limit.
def test_multibyte_idempotency_key_over_twenty_bytes_returns_422(
    api_client: TestClient,
) -> None:
    response = api_client.post(
        "/documents",
        json={
            "file_name": EXISTING_MEDIA_FILE,
            "idem_key": "é" * 11,
            "checksum": VALID_CHECKSUM,
        },
    )

    _assert_validation_error(
        response,
        field="idem_key",
        error_type="value_error",
        message="Value error, idem_key must not exceed 20 bytes",
    )


# what : Rejects fields outside the declared upload request contract.
# why   : ADDED - silently ignored fields can conceal client integration mistakes.
def test_unexpected_request_field_returns_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/documents",
        json={
            "file_name": EXISTING_MEDIA_FILE,
            "idem_key": _new_idempotency_key(),
            "checksum": VALID_CHECKSUM,
            "priority": "admin",
        },
    )

    _assert_validation_error(
        response,
        field="priority",
        error_type="extra_forbidden",
        message="Extra inputs are not permitted",
    )


# what : Rejects an empty filename before contacting R2 or Redis.
# why   : ADDED - an empty object key cannot identify a processable document.
def test_empty_file_name_returns_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/documents",
        json={
            "file_name": "",
            "idem_key": _new_idempotency_key(),
            "checksum": VALID_CHECKSUM,
        },
    )

    _assert_validation_error(
        response,
        field="file_name",
        error_type="string_too_short",
        message="String should have at least 1 character",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 3. SECURITY — documented patches only, no test functions
# ═══════════════════════════════════════════════════════════════════════════

# SECURITY-1 : Add authentication before exposing uploads outside the trusted deployment.
# SECURITY-2 : Add enforce_upload_rate_limit() because one client can exhaust Redis and OCR capacity.
# SECURITY-3 : Add validate_document_metadata() because existence alone does not restrict file type or size.
# SECURITY-4 : Add enforce_request_body_limit() because oversized JSON bodies can consume server memory.
# SECURITY-5 : Add validate_redis_key_characters() because control characters in idem_key hinder safe Redis operations.
# SECURITY-6 : Add sanitize_log_value() because attacker-controlled filenames can forge multiline log entries.
