"""LangGraph supervisor and specialist agents for EOC questions."""

from typing import Any

from langgraph.graph import END, START, StateGraph

from readforge.agents.provider import LLMProvider
from readforge.agents.state import (
    AgentIntent,
    AgentResponse,
    AgentResult,
    CaseInput,
    EOCState,
    RouterDecision,
)

SUPERVISOR_PROMPT = """
You are the intent router for questions about health-insurance Evidence of
Coverage documents. Return JSON only with this exact shape:
{"intents": ["coverage"], "clarification_question": null}

Choose one or more intents:
- coverage: CPT/HCPCS/ICD explanation, benefits, exclusions, or cost sharing
- prior_authorization: prior authorization, step therapy, or required evidence
- medical_necessity: denial or "not medically necessary" criteria
- referral: PCP, specialist referral, or network access rules

Route only what the question needs. Do not answer the question.
"""

SPECIALIST_PROMPTS: dict[AgentIntent, str] = {
    "coverage": """
You are the coverage specialist. Explain what the supplied evidence says about
benefits, exclusions, limitations, coding, and cost sharing. Never guarantee
that a claim will be paid.
""",
    "prior_authorization": """
You are the prior-authorization specialist. Identify authorization or step-
therapy requirements and produce a documentation-gap finding. Never invent
clinical history or insurer requirements.
""",
    "medical_necessity": """
You are the medical-necessity evidence specialist. Compare the stated denial or
criteria with supplied evidence. Do not make a clinical decision; identify what
is supported, missing, or conflicting and require human review.
""",
    "referral": """
You are the referral specialist. Identify PCP, specialist-referral, network,
and exception rules. Treat provider-network status as unknown unless the
supplied evidence explicitly confirms it.
""",
}

OUTPUT_INSTRUCTIONS = """
Use only the supplied evidence. Return JSON only:
{"findings": [{"conclusion": "...", "evidence_ids": ["E1"],
"missing_information": [], "conflicts": []}]}
Create at most five findings. Cite only supplied evidence IDs. Put every fact
needed to verify the conclusion into missing_information when it is absent.
"""

AGENT_NODES: dict[AgentIntent, str] = {
    "coverage": "coverage_agent",
    "prior_authorization": "prior_authorization_agent",
    "medical_necessity": "medical_necessity_agent",
    "referral": "referral_agent",
}


def normalize_case(state: EOCState) -> dict[str, CaseInput]:
    return {"case": CaseInput.model_validate(state["case"])}


def supervisor(state: EOCState) -> dict[str, Any]:
    case = CaseInput.model_validate(state["case"])
    missing = []
    if not case.plan_name:
        missing.append("the exact plan name")
    if case.coverage_year is None:
        missing.append("the coverage year")
    if not case.evidence:
        missing.append("relevant EOC or insurer evidence")
    if missing:
        return {
            "intents": [],
            "clarification_question": "Please provide " + ", ".join(missing) + ".",
        }

    decision = RouterDecision.model_validate(
        LLMProvider.invoke_json(
            SUPERVISOR_PROMPT,
            case.model_dump(mode="json"),
        )
    )
    return decision.model_dump()


def route_agents(state: EOCState) -> list[str]:
    if state.get("clarification_question"):
        return ["clarification"]
    return [AGENT_NODES[intent] for intent in state["intents"]]


def _run_specialist(
    state: EOCState, intent: AgentIntent
) -> dict[str, list[AgentResult]]:
    case = CaseInput.model_validate(state["case"])
    response = AgentResponse.model_validate(
        LLMProvider.invoke_json(
            SPECIALIST_PROMPTS[intent] + OUTPUT_INSTRUCTIONS,
            case.model_dump(mode="json"),
        )
    )
    result: AgentResult = {
        "agent": intent,
        "findings": [finding.model_dump() for finding in response.findings],
    }
    return {"agent_results": [result]}


def coverage_agent(state: EOCState) -> dict[str, list[AgentResult]]:
    return _run_specialist(state, "coverage")


def prior_authorization_agent(state: EOCState) -> dict[str, list[AgentResult]]:
    return _run_specialist(state, "prior_authorization")


def medical_necessity_agent(state: EOCState) -> dict[str, list[AgentResult]]:
    return _run_specialist(state, "medical_necessity")


def referral_agent(state: EOCState) -> dict[str, list[AgentResult]]:
    return _run_specialist(state, "referral")


def _confidence_level(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _score_finding(
    case: CaseInput,
    intent: AgentIntent,
    finding: dict[str, Any],
) -> dict[str, Any]:
    evidence_by_id = {item.evidence_id: item for item in case.evidence}
    requested_ids = list(dict.fromkeys(finding["evidence_ids"]))
    invalid_ids = [item for item in requested_ids if item not in evidence_by_id]
    cited_evidence = [
        evidence_by_id[item] for item in requested_ids if item in evidence_by_id
    ]
    conflicts = list(finding["conflicts"])
    conflicts.extend(f"Unknown evidence ID: {item}" for item in invalid_ids)
    if not cited_evidence:
        conflicts.append("No valid supporting evidence was cited.")

    plan_date_match = any(
        evidence.plan_name
        and case.plan_name
        and evidence.plan_name.casefold() == case.plan_name.casefold()
        and evidence.coverage_year == case.coverage_year
        for evidence in cited_evidence
    )
    breakdown = {
        "plan_and_year_match": 25 if plan_date_match else 0,
        "official_source_cited": 25
        if any(evidence.official for evidence in cited_evidence)
        else 0,
        "required_information_present": 25
        if not finding["missing_information"]
        else 0,
        "no_conflicting_evidence": 25 if not conflicts else 0,
    }
    score = sum(breakdown.values())
    return {
        "conclusion": finding["conclusion"],
        "citations": [
            {
                "evidence_id": evidence.evidence_id,
                "page_number": evidence.page_number,
                "document_type": evidence.document_type,
            }
            for evidence in cited_evidence
        ],
        "missing_information": finding["missing_information"],
        "conflicts": conflicts,
        "evidence_score": score,
        "confidence_level": _confidence_level(score),
        "score_breakdown": breakdown,
        "requires_human_review": score < 80 or intent == "medical_necessity",
    }


def score_results(state: EOCState) -> dict[str, dict[str, Any]]:
    case = CaseInput.model_validate(state["case"])
    results_by_agent = {result["agent"]: result for result in state["agent_results"]}
    scored_results = []
    all_scores = []
    requires_human_review = False

    for intent in state["intents"]:
        result = results_by_agent[intent]
        findings = [
            _score_finding(case, intent, finding) for finding in result["findings"]
        ]
        scored_results.append({"agent": intent, "findings": findings})
        all_scores.extend(finding["evidence_score"] for finding in findings)
        requires_human_review |= any(
            finding["requires_human_review"] for finding in findings
        )

    overall_score = min(all_scores)
    return {
        "final_response": {
            "results": scored_results,
            "overall_evidence_score": overall_score,
            "overall_confidence_level": _confidence_level(overall_score),
            "requires_human_review": requires_human_review,
            "clarification_question": None,
            "notice": (
                "This is an evidence-confidence score, not a probability that "
                "an insurer will approve or pay a claim."
            ),
        }
    }


def clarification(state: EOCState) -> dict[str, dict[str, Any]]:
    return {
        "final_response": {
            "results": [],
            "overall_evidence_score": None,
            "overall_confidence_level": None,
            "requires_human_review": False,
            "clarification_question": state["clarification_question"],
            "notice": "No conclusion was scored because required context is missing.",
        }
    }


workflow_builder = StateGraph(EOCState)
workflow_builder.add_node("normalize_case", normalize_case)
workflow_builder.add_node("supervisor", supervisor)
workflow_builder.add_node("coverage_agent", coverage_agent)
workflow_builder.add_node("prior_authorization_agent", prior_authorization_agent)
workflow_builder.add_node("medical_necessity_agent", medical_necessity_agent)
workflow_builder.add_node("referral_agent", referral_agent)
workflow_builder.add_node("score_results", score_results)
workflow_builder.add_node("clarification", clarification)

workflow_builder.add_edge(START, "normalize_case")
workflow_builder.add_edge("normalize_case", "supervisor")
workflow_builder.add_conditional_edges(
    "supervisor",
    route_agents,
    [*AGENT_NODES.values(), "clarification"],
)
for node in AGENT_NODES.values():
    workflow_builder.add_edge(node, "score_results")
workflow_builder.add_edge("score_results", END)
workflow_builder.add_edge("clarification", END)

workflow = workflow_builder.compile()
