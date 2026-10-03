"""Tests for the upload job lifecycle endpoint."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import readforge.controllers.job_controller as controller
from readforge.server import app
from readforge.utils.redis_utils import RedisJob, RedisJobStatus

client = TestClient(app, raise_server_exceptions=False)


class _Session:
    def __init__(self, job) -> None:
        self.job = job

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, *args):
        return self.job


def test_job_status_traces_queued_and_completed(monkeypatch) -> None:
    job_id = uuid4()
    created_at = datetime.now(UTC)
    monkeypatch.setattr(controller, "SessionLocal", lambda: _Session(None))

    async def no_retained_status(_job_id: str):
        return None

    monkeypatch.setattr(controller, "get_redis_job_status", no_retained_status)

    async def queued_job(_job_id: str):
        return RedisJob(
            file_name="documents/eoc.pdf",
            presigned_url="https://example.test/eoc.pdf",
            idem_key="request-1",
            checksum="0" * 64,
            job_id=str(job_id),
            created_at=created_at,
        )

    monkeypatch.setattr(controller, "get_job", queued_job)
    queued = client.get(f"/jobs/{job_id}")
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"

    document_id = uuid4()
    monkeypatch.setattr(
        controller,
        "SessionLocal",
        lambda: _Session(
            SimpleNamespace(
                id=job_id,
                document_id=document_id,
                status="completed",
                created_at=created_at,
                started_at=created_at,
                completed_at=created_at,
                error_message=None,
            )
        ),
    )
    completed = client.get(f"/jobs/{job_id}")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["document_id"] == str(document_id)


def test_job_status_uses_retained_redis_transition(monkeypatch) -> None:
    job_id = uuid4()
    document_id = uuid4()
    created_at = datetime.now(UTC)
    monkeypatch.setattr(controller, "SessionLocal", lambda: _Session(None))

    async def retained_status(_job_id: str):
        return RedisJobStatus(
            job_id=str(job_id),
            document_id=str(document_id),
            status="completed",
            created_at=created_at,
            completed_at=created_at,
        )

    monkeypatch.setattr(controller, "get_redis_job_status", retained_status)
    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["document_id"] == str(document_id)
