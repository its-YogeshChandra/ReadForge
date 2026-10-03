"""HTTP boundary for document-grounded EOC conversations."""

import asyncio
from datetime import UTC, date, datetime
from functools import partial
import re
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from readforge.agents.provider import LLMProviderError
from readforge.agents.workflow import workflow
from readforge.utils.db_utils import (
    ConversationDocumentMismatchError,
    ConversationNotFoundError,
    append_conversation_messages,
    load_conversation_messages,
)
from readforge.utils.embedding_utils import EmbeddingServiceError
from readforge.utils.retrieval import (
    DocumentNotFoundError,
    DocumentNotReadyError,
    retrieve_evidence,
)
from readforge.utils.tracing import trace

_COVERAGE_YEAR = re.compile(r"\b(?:20\d{2}|2100)\b")
# ponytail: process-local cap; use a Redis lease when the API runs multiple workers.
_AGENT_REQUEST_CAP = asyncio.Semaphore(2)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: UUID
    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=8000)
    plan_name: str | None = Field(default=None, max_length=200)
    coverage_year: int | None = Field(default=None, ge=2000, le=2100)
    service_date: date | None = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    evidence_count: int
    response: dict[str, Any]


def _assistant_content(response: dict[str, Any]) -> str:
    if response.get("clarification_question"):
        return response["clarification_question"]
    conclusions = [
        finding["conclusion"]
        for result in response.get("results", [])
        for finding in result.get("findings", [])
    ]
    return "\n".join(conclusions) or "No conclusion was produced."


def _case_from_request(
    request: ChatRequest,
    messages: list[dict],
) -> dict[str, Any]:
    case: dict[str, Any] = {
        "question": request.message,
        "plan_name": request.plan_name,
        "coverage_year": request.coverage_year,
        "service_date": request.service_date,
    }
    if not messages:
        return case

    last_message = messages[-1]
    prior_response = last_message.get("response", {})
    if (
        last_message.get("role") != "assistant"
        or not prior_response.get("clarification_question")
    ):
        return case

    previous_case = next(
        (
            message["case"]
            for message in reversed(messages)
            if message.get("role") == "user" and isinstance(message.get("case"), dict)
        ),
        None,
    )
    if previous_case is None:
        return case

    case["question"] = previous_case["question"]
    case["plan_name"] = request.plan_name or previous_case.get("plan_name")
    case["coverage_year"] = request.coverage_year or previous_case.get(
        "coverage_year"
    )
    case["service_date"] = request.service_date or previous_case.get("service_date")

    year_match = _COVERAGE_YEAR.search(request.message)
    if case["coverage_year"] is None and year_match:
        case["coverage_year"] = int(year_match.group())
    if case["plan_name"] is None:
        plan_name = _COVERAGE_YEAR.sub("", request.message).strip(" ,.;:-")
        if plan_name:
            case["plan_name"] = plan_name
    return case


async def chat(
    request: ChatRequest,
    correlation_id: str | None = None,
) -> ChatResponse:
    """Retrieve document evidence, run the agents, and persist both messages."""
    request_id = correlation_id or str(uuid4())
    trace(request_id, "chat.received", document_id=request.document_id)
    try:
        messages = await load_conversation_messages(
            request.document_id,
            request.conversation_id,
        )
        case = _case_from_request(request, messages)
        trace(request_id, "chat.retrieval_started")
        evidence = await retrieve_evidence(
            request.document_id,
            case["question"],
        )
        trace(request_id, "chat.retrieval_completed", evidence_count=len(evidence))
        if evidence:
            case["plan_name"] = case["plan_name"] or evidence[0].plan_name
            case["coverage_year"] = (
                case["coverage_year"] or evidence[0].coverage_year
            )
        case["evidence"] = [item.model_dump(mode="json") for item in evidence]
        trace(request_id, "chat.agents_started")
        async with _AGENT_REQUEST_CAP:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    partial(
                        workflow.invoke,
                        {"case": case},
                        config={"max_concurrency": 2},
                    )
                ),
                timeout=120,
            )
        response = result["final_response"]
        trace(
            request_id,
            "chat.agents_completed",
            agent_count=len(response.get("results", [])),
        )
        created_at = datetime.now(UTC).isoformat()
        stored_case = {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in case.items()
            if key != "evidence"
        }
        conversation_id = await append_conversation_messages(
            request.document_id,
            request.conversation_id,
            [
                {
                    "role": "user",
                    "content": request.message,
                    "created_at": created_at,
                    "case": stored_case,
                },
                {
                    "role": "assistant",
                    "content": _assistant_content(response),
                    "created_at": created_at,
                    "agents": [item["agent"] for item in response["results"]],
                    "response": response,
                },
            ],
        )
    except DocumentNotFoundError as error:
        trace(request_id, "chat.failed", error_type=type(error).__name__)
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except DocumentNotReadyError as error:
        trace(request_id, "chat.failed", error_type=type(error).__name__)
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except ConversationNotFoundError as error:
        trace(request_id, "chat.failed", error_type=type(error).__name__)
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except ConversationDocumentMismatchError as error:
        trace(request_id, "chat.failed", error_type=type(error).__name__)
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except (EmbeddingServiceError, LLMProviderError) as error:
        trace(request_id, "chat.failed", error_type=type(error).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    except TimeoutError as error:
        trace(request_id, "chat.failed", error_type=type(error).__name__)
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "Agent request timed out",
        ) from error
    except SQLAlchemyError as error:
        trace(request_id, "chat.failed", error_type=type(error).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Database is unavailable",
        ) from error

    trace(request_id, "chat.completed", conversation_id=conversation_id)
    return ChatResponse(
        conversation_id=conversation_id,
        evidence_count=len(evidence),
        response=response,
    )
