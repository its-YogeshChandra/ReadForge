"""Validated document plan-metadata updates."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError

from readforge.database import SessionLocal
from readforge.database.schema import Document

DocumentType = Literal[
    "eoc",
    "formulary",
    "prior_authorization",
    "clinical_policy",
    "provider_directory",
    "denial_letter",
    "other",
]


class DocumentMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    insurer: str | None = Field(default=None, min_length=1, max_length=200)
    plan_name: str | None = Field(default=None, min_length=1, max_length=200)
    plan_type: str | None = Field(default=None, min_length=1, max_length=50)
    jurisdiction_state: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z]{2}$",
    )
    coverage_year: int | None = Field(default=None, ge=2000, le=2100)
    effective_start: date | None = None
    effective_end: date | None = None
    document_type: DocumentType | None = None

    @field_validator("jurisdiction_state")
    @classmethod
    def uppercase_state(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode="after")
    def effective_dates_are_ordered(self) -> "DocumentMetadataRequest":
        if (
            self.effective_start
            and self.effective_end
            and self.effective_start > self.effective_end
        ):
            raise ValueError("effective_start must not be after effective_end")
        return self


class DocumentMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    document_id: UUID
    insurer: str | None
    plan_name: str | None
    plan_type: str | None
    jurisdiction_state: str | None
    coverage_year: int | None
    effective_start: date | None
    effective_end: date | None
    document_type: str
    source_verified: bool


async def update_document_metadata(
    document_id: UUID,
    request: DocumentMetadataRequest,
) -> DocumentMetadataResponse:
    """Update editable plan metadata without granting source-verification trust."""
    try:
        async with SessionLocal() as session:
            document = await session.get(Document, document_id)
            if document is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    "Document was not found",
                )

            changes = request.model_dump(exclude_unset=True)
            for field, value in changes.items():
                setattr(document, field, value)
            if (
                document.effective_start
                and document.effective_end
                and document.effective_start > document.effective_end
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "effective_start must not be after effective_end",
                )
            await session.commit()
            return DocumentMetadataResponse(
                document_id=document.id,
                insurer=document.insurer,
                plan_name=document.plan_name,
                plan_type=document.plan_type,
                jurisdiction_state=document.jurisdiction_state,
                coverage_year=document.coverage_year,
                effective_start=document.effective_start,
                effective_end=document.effective_end,
                document_type=document.document_type,
                source_verified=document.source_verified,
            )
    except SQLAlchemyError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Database is unavailable",
        ) from error
