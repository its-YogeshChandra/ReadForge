"""Hybrid retrieval of relevant OCR pages for an EOC question."""

import asyncio
import re
from uuid import UUID

from sqlalchemy import or_, select

from readforge.agents.state import Evidence
from readforge.database import SessionLocal
from readforge.database.schema import Document, DocumentChunk
from readforge.utils.embedding_utils import (
    EmbeddingsPayload,
    embed_text,
    embedding_model,
)

_MEDICAL_CODE = re.compile(
    r"(?<![A-Z0-9])(?:\d{5}|[A-Z]\d{4}|[A-Z]\d{2}(?:\.[A-Z0-9]{1,4})?)(?![A-Z0-9])",
    re.IGNORECASE,
)


class DocumentNotFoundError(LookupError):
    """The requested document does not exist."""


class DocumentNotReadyError(RuntimeError):
    """The requested document has no searchable OCR chunks yet."""


def _medical_codes(question: str) -> list[str]:
    return list(
        dict.fromkeys(match.upper() for match in _MEDICAL_CODE.findall(question))
    )


async def retrieve_evidence(
    document_id: UUID,
    question: str,
    *,
    limit: int = 8,
) -> list[Evidence]:
    """Return exact-code matches followed by nearest semantic page chunks."""
    model = embedding_model()
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise DocumentNotFoundError("Document was not found")
        chunk_id = await session.scalar(
            select(DocumentChunk.id)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.embedding_model == model,
            )
            .limit(1)
        )
    if chunk_id is None:
        raise DocumentNotReadyError("Document processing is not complete")

    query_embedding = await asyncio.to_thread(
        embed_text,
        EmbeddingsPayload(file_name=str(document_id), text_data=question),
    )
    codes = _medical_codes(question)

    async with SessionLocal() as session:
        exact: list[DocumentChunk] = []
        if codes:
            exact = list(
                (
                    await session.scalars(
                        select(DocumentChunk)
                        .where(
                            DocumentChunk.document_id == document_id,
                            DocumentChunk.embedding_model == model,
                            or_(
                                *(
                                    DocumentChunk.content.ilike(f"%{code}%")
                                    for code in codes
                                )
                            ),
                        )
                        .order_by(DocumentChunk.page_number, DocumentChunk.chunk_index)
                        .limit(limit * 2)
                    )
                ).all()
            )

        semantic = list(
            (
                await session.scalars(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_id == document_id,
                        DocumentChunk.embedding_model == model,
                    )
                    .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                    .limit(limit * 2)
                )
            ).all()
        )

    pages: dict[int, list[DocumentChunk]] = {}
    for chunk in [*exact, *semantic]:
        if chunk.page_number not in pages and len(pages) >= limit:
            continue
        page_chunks = pages.setdefault(chunk.page_number, [])
        if all(existing.content != chunk.content for existing in page_chunks):
            page_chunks.append(chunk)
    return [
        Evidence(
            evidence_id=f"chunk-{page_chunks[0].id}",
            page_number=page_number,
            content="\n\n".join(chunk.content for chunk in page_chunks),
            document_type=document.document_type,
            plan_name=document.plan_name,
            coverage_year=document.coverage_year,
            official=document.source_verified,
        )
        for page_number, page_chunks in pages.items()
    ]
