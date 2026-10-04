"""Tests for POST /chat.

PostgreSQL, the embedding service, and OpenRouter are never contacted; their
controller-facing functions are monkeypatched. Run with:
``uv run --with pytest pytest tests/test_chat_api.py -v``.
"""

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import readforge.controllers.chat_controller as controller
from readforge.agents.state import Evidence
from readforge.server import app
from readforge.utils.embedding_utils import EmbeddingServiceError
from readforge.utils.retrieval import DocumentNotFoundError, _medical_codes

client = TestClient(app, raise_server_exceptions=False)


def _payload() -> dict:
    return {
        "document_id": str(uuid4()),
        "message": "Is CPT 99213 covered?",
        "plan_name": "Example HMO",
        "coverage_year": 2026,
    }


def _workflow_response() -> dict:
    return {
        "results": [
            {
                "agent": "coverage",
                "findings": [
                    {
                        "conclusion": "The EOC lists the service as covered.",
                        "citations": [
                            {
                                "evidence_id": "chunk-7",
                                "page_number": 12,
                                "document_type": "eoc",
                            }
                        ],
                        "missing_information": [],
                        "conflicts": [],
                        "evidence_score": 75,
                        "confidence_level": "medium",
                        "score_breakdown": {},
                        "requires_human_review": True,
                    }
                ],
            }
        ],
        "overall_evidence_score": 75,
        "overall_confidence_level": "medium",
        "requires_human_review": True,
        "clarification_question": None,
        "notice": "Evidence-confidence score only.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. POSITIVE TESTS
# ═══════════════════════════════════════════════════════════════════════════


#what : Sends a valid document question through the real FastAPI route.
#why   : ADDED - pins retrieval, agent invocation, response shape, and JSONB writes.
def test_chat_retrieves_answers_and_persists_messages(monkeypatch) -> None:
    conversation_id = uuid4()
    saved: dict = {}

    async def fake_retrieve(*args, **kwargs) -> list[Evidence]:
        return [
            Evidence(
                evidence_id="chunk-7",
                page_number=12,
                content="Office visits are covered subject to cost sharing.",
                document_type="eoc",
                plan_name="Example HMO",
                coverage_year=2026,
                official=False,
            )
        ]

    def fake_invoke(*args, **kwargs) -> dict:
        return {"final_response": _workflow_response()}

    async def fake_append(document_id, requested_id, messages) -> object:
        saved.update(
            document_id=document_id,
            requested_id=requested_id,
            messages=messages,
        )
        return conversation_id

    monkeypatch.setattr(controller, "retrieve_evidence", fake_retrieve)
    monkeypatch.setattr(
        controller,
        "workflow",
        SimpleNamespace(invoke=fake_invoke),
    )
    monkeypatch.setattr(controller, "append_conversation_messages", fake_append)

    response = client.post("/chat", json=_payload())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["conversation_id"] == str(conversation_id)
    assert body["evidence_count"] == 1
    assert body["response"]["overall_evidence_score"] == 75
    assert [message["role"] for message in saved["messages"]] == [
        "user",
        "assistant",
    ]
    assert saved["messages"][1]["response"] == _workflow_response()


#what : Extracts CPT, HCPCS, and ICD-10 codes without treating a year as a code.
#why   : ADDED - exact code matches must rank ahead of merely similar pages.
def test_medical_code_extraction() -> None:
    assert _medical_codes("2026: CPT 99213, HCPCS J3490, ICD-10 M54.5") == [
        "99213",
        "J3490",
        "M54.5",
    ]


#what : Continues the original question after the agent asks for plan context.
#why   : ADDED - a clarification reply must resume, not become a new EOC question.
def test_chat_resumes_after_clarification(monkeypatch) -> None:
    conversation_id = uuid4()
    captured: dict = {}
    history = [
        {
            "role": "user",
            "content": "Is my office visit covered?",
            "case": {
                "question": "Is my office visit covered?",
                "plan_name": None,
                "coverage_year": None,
                "service_date": None,
            },
        },
        {
            "role": "assistant",
            "content": "Please provide the exact plan name and coverage year.",
            "response": {
                "clarification_question": (
                    "Please provide the exact plan name and coverage year."
                )
            },
        },
    ]

    async def fake_load(*args, **kwargs) -> list[dict]:
        return history

    async def fake_retrieve(document_id, question, **kwargs) -> list[Evidence]:
        captured["retrieval_question"] = question
        return [
            Evidence(
                evidence_id="chunk-7",
                page_number=12,
                content="Office visits are covered.",
                document_type="eoc",
                plan_name="Example HMO",
                coverage_year=2026,
                official=False,
            )
        ]

    def fake_invoke(payload, **kwargs) -> dict:
        captured["case"] = payload["case"]
        return {"final_response": _workflow_response()}

    async def fake_append(*args, **kwargs) -> object:
        return conversation_id

    monkeypatch.setattr(controller, "load_conversation_messages", fake_load)
    monkeypatch.setattr(controller, "retrieve_evidence", fake_retrieve)
    monkeypatch.setattr(
        controller,
        "workflow",
        SimpleNamespace(invoke=fake_invoke),
    )
    monkeypatch.setattr(controller, "append_conversation_messages", fake_append)
    payload = _payload()
    payload.update(
        conversation_id=str(conversation_id),
        message="Example HMO, 2026",
    )

    response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert captured["retrieval_question"] == "Is my office visit covered?"
    assert captured["case"]["plan_name"] == "Example HMO"
    assert captured["case"]["coverage_year"] == 2026


# ═══════════════════════════════════════════════════════════════════════════
# 2. NEGATIVE TESTS
# ═══════════════════════════════════════════════════════════════════════════


#what : Rejects an empty question at the API boundary.
#why   : ADDED - prevents empty paid embedding and LLM calls.
def test_chat_rejects_empty_message() -> None:
    payload = _payload()
    payload["message"] = ""

    response = client.post("/chat", json=payload)

    assert response.status_code == 422
    assert (
        response.json()["detail"][0]["msg"]
        == "String should have at least 1 character"
    )


#what : Returns not-found when the selected document does not exist.
#why   : ADDED - keeps missing data distinct from infrastructure failures.
def test_chat_returns_404_for_missing_document(monkeypatch) -> None:
    async def fake_retrieve(*args, **kwargs) -> list[Evidence]:
        raise DocumentNotFoundError("Document was not found")

    monkeypatch.setattr(controller, "retrieve_evidence", fake_retrieve)

    response = client.post("/chat", json=_payload())

    assert response.status_code == 404
    assert response.json() == {"detail": "Document was not found"}


#what : Returns bad-gateway when query embedding fails.
#why   : ADDED - an upstream outage must not look like a valid empty answer.
def test_chat_returns_502_for_embedding_failure(monkeypatch) -> None:
    async def fake_retrieve(*args, **kwargs) -> list[Evidence]:
        raise EmbeddingServiceError("Embedding request failed")

    monkeypatch.setattr(controller, "retrieve_evidence", fake_retrieve)

    response = client.post("/chat", json=_payload())

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Document search is temporarily unavailable"
    }


def test_chat_remembers_explicit_coverage_year(monkeypatch) -> None:
    saved: dict = {}

    async def fake_retrieve(*args, **kwargs) -> list[Evidence]:
        return [
            Evidence(
                evidence_id="chunk-7",
                page_number=12,
                content="Office visits are covered.",
                document_type="eoc",
                official=False,
            )
        ]

    async def fake_remember(document_id, coverage_year) -> bool:
        saved.update(document_id=document_id, coverage_year=coverage_year)
        return True

    def fake_invoke(payload, **kwargs) -> dict:
        saved["case"] = payload["case"]
        return {"final_response": _workflow_response()}

    async def fake_append(*args, **kwargs) -> object:
        return uuid4()

    monkeypatch.setattr(controller, "retrieve_evidence", fake_retrieve)
    monkeypatch.setattr(
        controller,
        "remember_document_coverage_year",
        fake_remember,
    )
    monkeypatch.setattr(
        controller,
        "workflow",
        SimpleNamespace(invoke=fake_invoke),
    )
    monkeypatch.setattr(controller, "append_conversation_messages", fake_append)
    payload = _payload()
    payload.pop("coverage_year")
    payload["message"] = "Coverage year is 2026. Are office visits covered?"

    response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert saved["coverage_year"] == 2026
    assert saved["case"]["coverage_year"] == 2026
    assert saved["case"]["evidence"][0]["coverage_year"] == 2026


# ═══════════════════════════════════════════════════════════════════════════
# 3. SECURITY — documented gaps
# ═══════════════════════════════════════════════════════════════════════════

# SECURITY-1 : POST /chat has no authenticated user or document ownership check.
# test_chat_rejects_another_users_document :
#     A caller who learns a document UUID could query private health-plan data.
#     Add authentication and compare Document.user_id, then assert a 404 response.

# SECURITY-2 : POST /chat has no request or per-user rate limit.
# test_chat_rate_limits_paid_upstream_calls :
#     An attacker could exhaust embedding and LLM quotas.
#     Add a gateway/user rate limit, then assert a 429 response.
