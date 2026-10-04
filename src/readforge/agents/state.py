"""Validated input and state types for EOC agents."""

from datetime import date
from operator import add
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentIntent = Literal[
    "coverage",
    "prior_authorization",
    "medical_necessity",
    "referral",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str = Field(min_length=1)
    page_number: int = Field(gt=0)
    content: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    plan_name: str | None = None
    coverage_year: int | None = Field(default=None, ge=2000, le=2100)
    official: bool


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1)
    plan_name: str | None = None
    coverage_year: int | None = Field(default=None, ge=2000, le=2100)
    service_date: date | None = None
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> "CaseInput":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_id values must be unique")
        return self


class RouterDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intents: list[AgentIntent] = Field(max_length=4)
    clarification_question: str | None

    @model_validator(mode="after")
    def decision_has_one_path(self) -> "RouterDecision":
        if bool(self.intents) == bool(self.clarification_question):
            raise ValueError(
                "return intents or a clarification question, but not both"
            )
        self.intents = list(dict.fromkeys(self.intents))
        return self


class AgentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conclusion: str = Field(min_length=1)
    evidence_ids: list[str]
    missing_information: list[str] = Field(
        description=(
            "Document facts required to answer the question that the supplied "
            "evidence does not establish."
        )
    )
    user_context: list[str] = Field(
        description=(
            "Optional insured-specific details needed only to personalize or "
            "apply the document answer."
        )
    )
    conflicts: list[str]


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[AgentFinding] = Field(min_length=1, max_length=5)


class AgentResult(TypedDict):
    agent: AgentIntent
    findings: list[dict[str, Any]]


class EOCState(TypedDict):
    case: CaseInput | dict[str, Any]
    intents: NotRequired[list[AgentIntent]]
    clarification_question: NotRequired[str | None]
    agent_results: Annotated[list[AgentResult], add]
    final_response: NotRequired[dict[str, Any]]
