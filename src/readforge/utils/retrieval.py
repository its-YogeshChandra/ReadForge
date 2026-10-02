"""Hybrid retrieval of relevant OCR pages for an EOC question."""

import asyncio
import re
from uuid import UUID

from sqlalchemy import or_, select

from readforge.agents.state import Evidence
from readforge.database import SessionLocal
from readforge.database.schema import Document, DocumentChunk
from readforge.utils.embedding_utils import EmbeddingsPayload, embed_text

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
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise DocumentNotFoundError("Document was not found")
        chunk_id = await session.scalar(
            select(DocumentChunk.id)
            .where(DocumentChunk.document_id == document_id)
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
                            or_(
                                *(
                                    DocumentChunk.content.ilike(f"%{code}%")
                                    for code in codes
                                )
                            ),
                        )
                        .order_by(DocumentChunk.page_number, DocumentChunk.chunk_index)
                        .limit(limit)
                    )
                ).all()
            )

        semantic = list(
            (
                await session.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                    .limit(limit)
                )
            ).all()
        )

    chunks = list({chunk.id: chunk for chunk in [*exact, *semantic]}.values())[:limit]
    return [
        Evidence(
            evidence_id=f"chunk-{chunk.id}",
            page_number=chunk.page_number,
            content=chunk.content,
            document_type=document.document_type,
            plan_name=document.plan_name,
            coverage_year=document.coverage_year,
            official=document.source_verified,
        )
        for chunk in chunks
    ]
