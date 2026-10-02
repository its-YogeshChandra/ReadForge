"""Tests for PATCH /documents/{id}/metadata.

PostgreSQL is never contacted; the controller session is replaced with a small
in-memory fake. Run with:
``uv run --with pytest pytest tests/test_document_metadata_api.py -v``.
"""

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import readforge.controllers.document_metadata_controller as controller
from readforge.server import app

client = TestClient(app, raise_server_exceptions=False)


class _Session:
    def __init__(self, document) -> None:
        self.document = document

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, *args):
        return self.document

    async def commit(self) -> None:
        return None


def _document(document_id):
    return SimpleNamespace(
        id=document_id,
        insurer=None,
        plan_name=None,
        plan_type=None,
        jurisdiction_state=None,
        coverage_year=None,
        effective_start=None,
        effective_end=None,
        document_type="eoc",
        source_verified=False,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. POSITIVE TESTS
# ═══════════════════════════════════════════════════════════════════════════


#what : Stores validated EOC plan metadata through the real FastAPI route.
#why   : ADDED - retrieval and scoring need stable plan/year metadata.
def test_update_document_metadata(monkeypatch) -> None:
    document_id = uuid4()
    document = _document(document_id)
    monkeypatch.setattr(controller, "SessionLocal", lambda: _Session(document))

    response = client.patch(
        f"/documents/{document_id}/metadata",
        json={
            "insurer": "Example Health",
            "plan_name": "Example HMO",
            "plan_type": "HMO",
            "jurisdiction_state": "ca",
            "coverage_year": 2026,
            "effective_start": "2026-01-01",
            "effective_end": "2026-12-31",
            "document_type": "eoc",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "document_id": str(document_id),
        "insurer": "Example Health",
        "plan_name": "Example HMO",
        "plan_type": "HMO",
        "jurisdiction_state": "CA",
        "coverage_year": 2026,
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
        "document_type": "eoc",
        "source_verified": False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. NEGATIVE TESTS
# ═══════════════════════════════════════════════════════════════════════════


#what : Rejects an effective period whose end precedes its start.
#why   : ADDED - invalid dates would make plan-year scoring misleading.
def test_update_document_metadata_rejects_reversed_dates() -> None:
    response = client.patch(
        f"/documents/{uuid4()}/metadata",
        json={
            "effective_start": "2026-12-31",
            "effective_end": "2026-01-01",
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"][0]["msg"]
        == "Value error, effective_start must not be after effective_end"
    )


#what : Returns not-found when metadata targets an unknown document.
#why   : ADDED - missing data is not a successful no-op.
def test_update_document_metadata_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(controller, "SessionLocal", lambda: _Session(None))

    response = client.patch(
        f"/documents/{uuid4()}/metadata",
        json={"plan_name": "Example HMO"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document was not found"}


#what : Prevents callers from self-asserting that a source is official.
#why   : ADDED - source trust must come from an administrative provenance check.
def test_update_document_metadata_rejects_source_verified() -> None:
    response = client.patch(
        f"/documents/{uuid4()}/metadata",
        json={"source_verified": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Extra inputs are not permitted"


# ═══════════════════════════════════════════════════════════════════════════
# 3. SECURITY — documented gaps
# ═══════════════════════════════════════════════════════════════════════════

# SECURITY-1 : The project has no authentication provider or trusted identity.
# test_metadata_rejects_non_owner :
#     Anyone who learns a UUID could change plan metadata and influence answers.
#     Add authentication middleware and compare Document.user_id, then assert 404.
